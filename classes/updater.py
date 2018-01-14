# -*- coding: utf-8 -*-
# Copyright (c) 2017-2018, Leo Moll

# -- Imports ------------------------------------------------
import os, stat, urllib2, subprocess, ijson, datetime, time
import xml.etree.ElementTree as etree

from operator import itemgetter
from classes.store import Store
from classes.exceptions import DatabaseCorrupted
from classes.exceptions import DatabaseLost

# -- Unpacker support ---------------------------------------
upd_can_bz2 = False
upd_can_gz  = False

try:
	import bz2
	upd_can_bz2 = True
except ImportError:
	pass

try:
	import gzip
	upd_can_gz = True
except ImportError:
	pass

# -- Constants ----------------------------------------------
FILMLISTE_AKT_URL = 'https://res.mediathekview.de/akt.xml'
FILMLISTE_DIF_URL = 'https://res.mediathekview.de/diff.xml'

# -- Classes ------------------------------------------------
class MediathekViewUpdater( object ):
	def __init__( self, logger, notifier, settings, monitor = None ):
		self.logger		= logger
		self.notifier	= notifier
		self.settings	= settings
		self.monitor	= monitor
		self.db			= None
		self.use_xz     = self._find_xz()

	def Init( self ):
		if self.db is not None:
			self.Exit()
		self.db = Store( self.logger, self.notifier, self.settings )
		self.db.Init()

	def Exit( self ):
		if self.db is not None:
			self.db.Exit()
			del self.db
			self.db = None

	def IsEnabled( self ):
		return self.settings.updenabled

	def GetCurrentUpdateOperation( self ):
		if not self.IsEnabled() or self.db is None:
			# update disabled or not possible
			self.logger.info( 'update disabled or not possible' )
			return 0
		status = self.db.GetStatus()
		tsnow = int( time.time() )
		tsold = status['lastupdate']
		dtnow = datetime.datetime.fromtimestamp( tsnow ).date()
		dtold = datetime.datetime.fromtimestamp( tsold ).date()
		if status['status'] == 'UNINIT':
			# database not initialized
			self.logger.debug( 'database not initialized' )
			return 0
		elif status['status'] == "UPDATING" and tsnow - tsold > 86400:
			# process was probably killed during update
			self.logger.info( 'Stuck update pretending to run since epoch {} reset', tsold )
			self.db.UpdateStatus( 'ABORTED' )
			return 0
		elif status['status'] == "UPDATING":
			# already updating
			self.logger.debug( 'already updating' )
			return 0
		elif tsnow - tsold < self.settings.updinterval:
			# last update less than the configured update interval. do nothing
			self.logger.debug( 'last update less than the configured update interval. do nothing' )
			return 0
		elif dtnow != dtold:
			# last update was not today. do full update once a day
			self.logger.debug( 'last update was not today. do full update once a day' )
			return 1
		elif status['status'] == "ABORTED" and status['fullupdate'] == 1:
			# last full update was aborted - full update needed
			self.logger.debug( 'last full update was aborted - full update needed' )
			return 1
		else:
			# do differential update
			self.logger.debug( 'do differential update' )
			return 2

	def Update( self, full ):
		if self.db is None:
			return
		if self.db.SupportsUpdate():
			if self.GetNewestList( full ):
				self.Import( full )

	def Import( self, full ):
		( url, compfile, destfile, avgrecsize ) = self._get_update_info( full )
		if not _file_exists( destfile ):
			self.logger.error( 'File {} does not exists', destfile )
			return False
		# estimate number of records in update file
		records = int( _file_size( destfile ) / avgrecsize )
		if not self.db.ftInit():
			self.logger.warn( 'Failed to initialize update. Maybe a concurrency problem?' )
			return False
		try:
			self.logger.info( 'Starting import of approx. {} records from {}', records, destfile )
			file = open( destfile, 'r' )
			parser = ijson.parse( file )
			flsm = 0
			flts = 0
			( self.tot_chn, self.tot_shw, self.tot_mov ) = self._update_start( full )
			self.notifier.ShowUpdateProgress()
			for prefix, event, value in parser:
				if ( prefix, event ) == ( "X", "start_array" ):
					self._init_record()
				elif ( prefix, event ) == ( "X", "end_array" ):
					self._end_record( records )
					if self.count % 100 == 0 and self.monitor.abortRequested():
						# kodi is shutting down. Close all
						file.close()
						self._update_end( full, 'ABORTED' )
						self.notifier.CloseUpdateProgress()
						return True
				elif ( prefix, event ) == ( "X.item", "string" ):
					if value is not None:
#						self._add_value( value.strip().encode('utf-8') )
						self._add_value( value.strip() )
					else:
						self._add_value( "" )
				elif ( prefix, event ) == ( "Filmliste", "start_array" ):
					flsm += 1
				elif ( prefix, event ) == ( "Filmliste.item", "string" ):
					flsm += 1
					if flsm == 2 and value is not None:
						# this is the timestmap of this database update
						try:
							fldt = datetime.datetime.strptime( value.strip(), "%d.%m.%Y, %H:%M" )
							flts = int( time.mktime( fldt.timetuple() ) )
							self.db.UpdateStatus( filmupdate = flts )
							self.logger.info( 'Filmliste dated {}', value.strip() )
						except TypeError:
							# SEE: https://forum.kodi.tv/showthread.php?tid=112916&pid=1214507#pid1214507
							# Wonderful. His name is also Leopold
							try:
								flts = int( time.mktime( time.strptime( value.strip(), "%d.%m.%Y, %H:%M" ) ) )
								self.db.UpdateStatus( filmupdate = flts )
								self.logger.info( 'Filmliste dated {}', value.strip() )
							except Exception as err:
								# If the universe hates us...
								self.logger.debug( 'Could not determine date "{}" of filmliste: {}', value.strip(), err )
						except ValueError as err:
							pass

			file.close()
			self._update_end( full, 'IDLE' )
			self.logger.info( 'Import of {} finished', destfile )
			self.notifier.CloseUpdateProgress()
			return True
		except KeyboardInterrupt:
			file.close()
			self._update_end( full, 'ABORTED' )
			self.logger.info( 'Interrupted by user' )
			self.notifier.CloseUpdateProgress()
			return True
		except DatabaseCorrupted as err:
			self.logger.error( '{}', err )
			self.notifier.CloseUpdateProgress()
			file.close()
		except DatabaseLost as err:
			self.logger.error( '{}', err )
			self.notifier.CloseUpdateProgress()
			file.close()
		except IOError as err:
			self.logger.error( 'Error {} wile processing {}', err, destfile )
			try:
				self._update_end( full, 'ABORTED' )
				self.notifier.CloseUpdateProgress()
				file.close()
			except Exception as err:
				pass
			return False

	def GetNewestList( self, full ):
		( url, compfile, destfile, avgrecsize ) = self._get_update_info( full )
		if url is None:
			self.logger.error( 'No suitable archive extractor available for this system' )
			self.notifier.ShowMissingExtractorError()
			return False

		# get mirrorlist
		self.logger.info( 'Opening {}', url )
		try:
			data = urllib2.urlopen( url ).read()
		except urllib2.URLError as err:
			self.logger.error( 'Failure opening {}', url )
			self.notifier.ShowDownloadError( url, err )
			return False

		root = etree.fromstring ( data )
		urls = []
		for server in root.findall( 'Server' ):
			try:
				URL = server.find( 'URL' ).text
				Prio = server.find( 'Prio' ).text
				urls.append( ( self._get_update_url( URL ), Prio ) )
				self.logger.info( 'Found mirror {} (Priority {})', URL, Prio )
			except AttributeError:
				pass
		urls = sorted( urls, key = itemgetter( 1 ) )
		urls = [ url[0] for url in urls ]
		result = None

		# cleanup downloads
		self.logger.info( 'Cleaning up old downloads...' )
		self._file_remove( compfile )
		self._file_remove( destfile )

		# download filmliste
		self.notifier.ShowDownloadProgress()
		lasturl = ''
		for url in urls:
			try:
				lasturl = url
				self.logger.info( 'Trying to download {} from {}...', os.path.basename( compfile ), url )
				self.notifier.UpdateDownloadProgress( 0, url )
				result = _url_retrieve( url, filename = compfile, reporthook = self._reporthook )
				break
			except urllib2.URLError as err:
				self.logger.error( 'Failure downloading {}', url )
			except Exception as err:
				self.logger.error( 'Failure writng {}', url )
		if result is None:
			self.logger.info( 'No file downloaded' )
			self.notifier.CloseDownloadProgress()
			self.notifier.ShowDownloadError( lasturl, err )
			return False

		# decompress filmliste
		if self.use_xz is True:
			xzbin = self._find_xz()
			self.logger.info( 'Trying to decompress xz file...' )
			retval = subprocess.call( [ xzbin, '-d', compfile ] )
			self.logger.info( 'Return {}', retval )
		elif upd_can_bz2 is True:
			self.logger.info( 'Trying to decompress bz2 file...' )
			retval = _decompress_bz2( compfile, destfile )
			self.logger.info( 'Return {}', retval )
		elif upd_can_gz is True:
			self.logger.info( 'Trying to decompress gz file...' )
			retval = _decompress_gz( compfile, destfile )
			self.logger.info( 'Return {}', retval )
		else:
			# should nebver reach
			pass

		self.notifier.CloseDownloadProgress()
		return retval == 0 and _file_exists( destfile )

	def _get_update_info( self, full ):
		if self.use_xz is True:
			ext = 'xz'
		elif upd_can_bz2 is True:
			ext = 'bz2'
		elif upd_can_gz is True:
			ext = 'gz'
		else:
			return ( None, None, None, 0, )
  
		if full:
			return (
				FILMLISTE_AKT_URL,
				os.path.join( self.settings.datapath, 'Filmliste-akt.' + ext ),
				os.path.join( self.settings.datapath, 'Filmliste-akt' ),
				600,
			)
		else:
			return (
				FILMLISTE_DIF_URL,
				os.path.join( self.settings.datapath, 'Filmliste-diff.' + ext ),
				os.path.join( self.settings.datapath, 'Filmliste-diff' ),
				700,
			)

	def _get_update_url( self, url ):
		if self.use_xz is True:
			return url
		elif upd_can_bz2 is True:
			return os.path.splitext( url )[0] + '.bz2'
		elif upd_can_gz is True:
			return os.path.splitext( url )[0] + '.gz'
		else:
			# should never happen since it will not be called
			return None

	def _find_xz( self ):
		for xzbin in [ '/bin/xz', '/usr/bin/xz', '/usr/local/bin/xz' ]:
			if _file_exists( xzbin ):
				return xzbin
		return None

	def _file_remove( self, name ):
		if _file_exists( name ):
			try:
				os.remove( name )
				return True
			except OSError as err:
				self.logger.error( 'Failed to remove {}: error {}', name, err )
		return False

	def _reporthook( self, blockcount, blocksize, totalsize ):
		downloaded = blockcount * blocksize
		if totalsize > 0:
			percent = int( (downloaded * 100) / totalsize )
			self.notifier.UpdateDownloadProgress( percent )
		self.logger.debug( 'Downloading blockcount={}, blocksize={}, totalsize={}', blockcount, blocksize, totalsize )

	def _update_start( self, full ):
		self.logger.info( 'Initializing update...' )
		self.add_chn = 0
		self.add_shw = 0
		self.add_mov = 0
		self.add_chn = 0
		self.add_shw = 0
		self.add_mov = 0
		self.del_chn = 0
		self.del_shw = 0
		self.del_mov = 0
		self.index = 0
		self.count = 0
		self.film = {
			"channel": "",
			"show": "",
			"title": "",
			"aired": "1980-01-01 00:00:00",
			"duration": "00:00:00",
			"size": 0,
			"description": "",
			"website": "",
			"url_sub": "",
			"url_video": "",
			"url_video_sd": "",
			"url_video_hd": "",
			"airedepoch": 0,
			"geo": ""
		}
		return self.db.ftUpdateStart( full )

	def _update_end( self, full, status ):
		self.logger.info( 'Added: channels:%d, shows:%d, movies:%d ...' % ( self.add_chn, self.add_shw, self.add_mov ) )
		( self.del_chn, self.del_shw, self.del_mov, self.tot_chn, self.tot_shw, self.tot_mov ) = self.db.ftUpdateEnd( full and status == 'IDLE' )
		self.logger.info( 'Deleted: channels:%d, shows:%d, movies:%d' % ( self.del_chn, self.del_shw, self.del_mov ) )
		self.logger.info( 'Total: channels:%d, shows:%d, movies:%d' % ( self.tot_chn, self.tot_shw, self.tot_mov ) )
		self.db.UpdateStatus(
			status,
			int( time.time() ) if status != 'ABORTED' else None,
			None,
			1 if full else 0,
			self.add_chn, self.add_shw, self.add_mov,
			self.del_chn, self.del_shw, self.del_mov,
			self.tot_chn, self.tot_shw, self.tot_mov
		)

	def _init_record( self ):
		self.index = 0
		self.film["title"] = ""
		self.film["aired"] = "1980-01-01 00:00:00"
		self.film["duration"] = "00:00:00"
		self.film["size"] = 0
		self.film["description"] = ""
		self.film["website"] = ""
		self.film["url_sub"] = ""
		self.film["url_video"] = ""
		self.film["url_video_sd"] = ""
		self.film["url_video_hd"] = ""
		self.film["airedepoch"] = 0
		self.film["geo"] = ""

	def _end_record( self, records ):
		if self.count % 1000 == 0:
			percent = int( self.count * 100 / records )
			self.logger.info( 'In progress (%d%%): channels:%d, shows:%d, movies:%d ...' % ( percent, self.add_chn, self.add_shw, self.add_mov ) )
			self.notifier.UpdateUpdateProgress( percent if percent <= 100 else 100, self.count, self.add_chn, self.add_shw, self.add_mov )
			self.db.UpdateStatus(
				add_chn = self.add_chn,
				add_shw = self.add_shw,
				add_mov = self.add_mov,
				tot_chn = self.tot_chn + self.add_chn,
				tot_shw = self.tot_shw + self.add_shw,
				tot_mov = self.tot_mov + self.add_mov
			)
			self.count = self.count + 1
			( filmid, cnt_chn, cnt_shw, cnt_mov ) = self.db.ftInsertFilm( self.film, True )
		else:
			self.count = self.count + 1
			( filmid, cnt_chn, cnt_shw, cnt_mov ) = self.db.ftInsertFilm( self.film, False )
		self.add_chn += cnt_chn
		self.add_shw += cnt_shw
		self.add_mov += cnt_mov

	def _add_value( self, val ):
		if self.index == 0:
			if val != "":
				self.film["channel"] = val
		elif self.index == 1:
			if val != "":
				self.film["show"] = val[:255]
		elif self.index == 2:
			self.film["title"] = val[:255]
		elif self.index == 3:
			if len(val) == 10:
				self.film["aired"] = val[6:] + '-' + val[3:5] + '-' + val[:2]
		elif self.index == 4:
			if ( self.film["aired"] != "1980-01-01 00:00:00" ) and ( len(val) == 8 ):
				self.film["aired"] = self.film["aired"] + " " + val
		elif self.index == 5:
			if len(val) == 8:
				self.film["duration"] = val
		elif self.index == 6:
			if val != "":
				self.film["size"] = int(val)
		elif self.index == 7:
			self.film["description"] = val
		elif self.index == 8:
			self.film["url_video"] = val
		elif self.index == 9:
			self.film["website"] = val
		elif self.index == 10:
			self.film["url_sub"] = val
		elif self.index == 12:
			self.film["url_video_sd"] = self._make_url(val)
		elif self.index == 14:
			self.film["url_video_hd"] = self._make_url(val)
		elif self.index == 16:
			if val != "":
				self.film["airedepoch"] = int(val)
		elif self.index == 18:
			self.film["geo"] = val
		self.index = self.index + 1

	def _make_url( self, val ):
		x = val.split( '|' )
		if len( x ) == 2:
			cnt = int( x[0] )
			return self.film["url_video"][:cnt] + x[1]
		else:
			return val


# -- Functions ----------------------------------------------

def _file_exists( name ):
	try:
		s = os.stat( name )
		return stat.S_ISREG( s.st_mode )
	except OSError as err:
		return False

def _file_size( name ):
	try:
		s = os.stat( name )
		return s.st_size
	except OSError as err:
		return 0

def _url_retrieve( url, filename, reporthook, chunk_size = 8192 ):
	f = open( filename, 'wb' )
	u = urllib2.urlopen( url )

	total_size = int( u.info().getheader( 'Content-Length' ).strip() ) if u.info() and u.info().getheader( 'Content-Length' ) else 0
	total_chunks = 0

	while True:
		reporthook( total_chunks, chunk_size, total_size )
		chunk = u.read( chunk_size )
		if not chunk:
			break
		f.write( chunk )
		total_chunks += 1
	f.close()
	return ( filename, [], )

def _decompress_bz2( sourcefile, destfile ):
	blocksize = 8192
	try:
		with open( destfile, 'wb' ) as df, open( sourcefile, 'rb' ) as sf:
			decompressor = bz2.BZ2Decompressor()
			for data in iter( lambda : sf.read( blocksize ), b'' ):
				df.write( decompressor.decompress( data ) )
	except Exception as err:
		self.logger.error( 'bz2 decompression failed: {}'.format( err ) )
		return -1
	return 0

def _decompress_gz( sourcefile, destfile ):
	blocksize = 8192
	try:
		with open( destfile, 'wb' ) as df, gzip.open( sourcefile ) as sf:
			for data in iter( lambda : sf.read( blocksize ), b'' ):
				df.write( data )
	except Exception as err:
		self.logger.error( 'gz decompression failed: {}'.format( err ) )
		return -1
	return 0
