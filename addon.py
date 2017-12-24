# -*- coding: utf-8 -*-
# Copyright 2017 RauteMusik GmbH, Leo Moll
#

# -- Imports ------------------------------------------------
import json,os,sys,urlparse,urllib,urllib2,requests,httplib,hashlib,time,string
import xbmc,xbmcplugin,xbmcgui,xbmcaddon,xbmcvfs
import mysql.connector


# -- Constants ----------------------------------------------
ADDON_ID = 'plugin.video.mediathekview'

# -- Settings -----------------------------------------------
settings = xbmcaddon.Addon( id=ADDON_ID )

# -- I18n ---------------------------------------------------
language = xbmcaddon.Addon( id=ADDON_ID ).getLocalizedString

# -- Functions ----------------------------------------------

# -- Classes ------------------------------------------------
class MediathekView( xbmcaddon.Addon ):

	def __init__( self ):
		self.language	= self.getLocalizedString
		self.addon_id	= self.getAddonInfo( 'id' )
		self.icon		= self.getAddonInfo( 'icon' )
		self.fanart		= self.getAddonInfo( 'fanart' )
		self.version	= self.getAddonInfo( 'version' )
		self.path		= self.getAddonInfo( 'path' )

	def log( self,message, level=xbmc.LOGDEBUG ):
		xbmc.log( "[%s-%s]: %s" %( self.addon_id, self.version, message ), level = level )

	def notice( self,message ):
		self.log( message, xbmc.LOGNOTICE )

	def warning( self,message ):
		self.log( message, xbmc.LOGWARNING )

	def error( self,message ):
		self.log( message, xbmc.LOGERROR )

	def build_url( self, query ):
		return self.base_url + '?' + urllib.urlencode( query )

	def addChannel( self, key, value ):
		li = xbmcgui.ListItem( label = value )
		xbmcplugin.addDirectoryItem(
			handle	= self.addon_handle,
			url		= self.build_url( {
				'mode': "channel",
				'channel': key
			} ),
			listitem = li,
			isFolder = True
		)

	def addInitialInChannel( self, channelid, letter, count ):
		li = xbmcgui.ListItem( label = '%s (%d)' % ( letter if letter != ' ' else ' No Title', count ) )
		xbmcplugin.addDirectoryItem(
			handle	= self.addon_handle,
			url		= self.build_url( {
				'mode': "channel-initial",
				'channel': channelid,
				'letter': letter,
				'count': count
			} ),
			listitem = li,
			isFolder = True
		)

	def addChannelList( self ):
		xbmcplugin.addSortMethod( self.addon_handle, xbmcplugin.SORT_METHOD_LABEL )
		self.addChannel( 0, " All" )
		cursor = self.conn.cursor()
		query = "SELECT id,channel FROM channel"
		cursor.execute( query )
		for ( id, channel ) in cursor:
			self.addChannel( id, channel )
		cursor.close()
		xbmcplugin.endOfDirectory( self.addon_handle )

	def addInitialListInChannel( self, channelid ):
		xbmcplugin.addSortMethod( self.addon_handle, xbmcplugin.SORT_METHOD_LABEL )
		cursor = self.conn.cursor()
		if channelid == '0':
			cursor.execute(
				'SELECT LEFT(search,1) AS letter,COUNT(*) AS count FROM category GROUP BY LEFT(search,1) ORDER BY LEFT(search,1)'
			)
		else:
			cursor.execute(
				'SELECT LEFT(search,1) AS letter,COUNT(*) AS count FROM category WHERE channelid=%s GROUP BY LEFT(search,1) ORDER BY LEFT(search,1)' %
				channelid
			)
		for ( letter, count ) in cursor:
			self.addInitialInChannel( channelid, letter, count )
		cursor.close()
		xbmcplugin.endOfDirectory( self.addon_handle )

	def addFilm( self, title, category, description, seconds, size, aired, url_video, url_video_sd, url_video_hd ):
		# get the best url
		videourl = url_video_hd if url_video_hd != "" else url_video if url_video != "" else url_video_sd
		# exit if no url supplied
		if videourl == "":
			return

		li = xbmcgui.ListItem(
			label = title,
			label2 = title
		)
		airedstring = '%s' % aired
		aireddate = airedstring[8:10] + '-' + airedstring[5:7] + '-' + airedstring[:4]
		li.setInfo( type = 'video', infoLabels = {
			'title' : title,
			'tvshowtitle' : category,
			'size' : size * 1024 * 1024,
			'date' : aireddate,
			'aired' : airedstring,
			'dateadded' : airedstring,
			'plot' : description,
			'duration' : seconds
		} )
		li.setProperty( 'IsPlayable', 'true' )

		xbmcplugin.addDirectoryItem(
			handle	= self.addon_handle,
			url		= videourl,
			listitem = li,
			isFolder = False
		)

	def addFilmlistInChannelAndCategory( self, channelid, categoryid ):
		xbmcplugin.addSortMethod( self.addon_handle, xbmcplugin.SORT_METHOD_TITLE )
		xbmcplugin.addSortMethod( self.addon_handle, xbmcplugin.SORT_METHOD_DATE )
		xbmcplugin.addSortMethod( self.addon_handle, xbmcplugin.SORT_METHOD_DURATION )
		xbmcplugin.addSortMethod( self.addon_handle, xbmcplugin.SORT_METHOD_SIZE )
		cursor = self.conn.cursor()
		cursor.execute(
			"SELECT title,category,description,TIME_TO_SEC(duration) AS seconds,size,aired,url_video,url_video_sd,url_video_hd FROM film LEFT JOIN category ON category.id=film.categoryid WHERE categoryid=%s ORDER BY TITLE" %
			categoryid
		)
		for ( title, category, description, seconds, size, aired, url_video, url_video_sd, url_video_hd ) in cursor:
			self.addFilm( title, category, description, seconds, size, aired, url_video, url_video_sd, url_video_hd )
		cursor.close()
		xbmcplugin.endOfDirectory( self.addon_handle )

	def addCategoryInChannel( self, categoryid, channelid, category ):
		li = xbmcgui.ListItem( label = category )
		xbmcplugin.addDirectoryItem(
			handle	= self.addon_handle,
			url		= self.build_url( {
				'mode': "channel-category",
				'channel': channelid,
				'category': categoryid
			} ),
			listitem = li,
			isFolder = True
		)

	def addCategoryListInChannelAndInitial( self, channelid, letter, count ):
		cursor = self.conn.cursor()
		if channelid == '0':
			cursor.execute(
				"SELECT id,channelid,category FROM category WHERE search LIKE '%s%%' ORDER BY category" %
				letter
			)
		else:
			cursor.execute(
				"SELECT id,channelid,category FROM category WHERE channelid=%s AND search LIKE '%s%%' ORDER BY category" %
				( channelid, letter )
			)
		for ( id, channelid, category ) in cursor:
			self.addCategoryInChannel( id, channelid, category )
		cursor.close()
		xbmcplugin.endOfDirectory( self.addon_handle )
		xbmcplugin.addSortMethod( self.addon_handle, xbmcplugin.SORT_METHOD_LABEL )

	def Init( self ):
		self.notice( "Init" );
		self.base_url		= sys.argv[0]
		self.addon_handle	= int( sys.argv[1] )
		self.args			= urlparse.parse_qs( sys.argv[2][1:] )
		self.conn			= mysql.connector.connect(
			host		= xbmcplugin.getSetting( self.addon_handle, 'dbhost' ),
			user		= xbmcplugin.getSetting( self.addon_handle, 'dbuser' ),
			password	= xbmcplugin.getSetting( self.addon_handle, 'dbpass' ),
			database	= xbmcplugin.getSetting( self.addon_handle, 'dbdata' )
		)

	def Do( self ):
		mode = self.args.get('mode', None)
		if mode is None:
			self.addChannelList()
		elif mode[0] == 'channel':
			channel = self.args.get( 'channel', [0] )
			self.addInitialListInChannel( channel[0] )
		elif mode[0] == 'channel-initial':
			channel = self.args.get( 'channel', [0] )
			letter = self.args.get( 'letter', [None] )
			count = self.args.get( 'count', [0] )
			self.addCategoryListInChannelAndInitial( channel[0], letter[0], count[0] )
		elif mode[0] == 'channel-category':
			channel = self.args.get( 'channel', [0] )
			category = self.args.get( 'category', [0] )
			self.addFilmlistInChannelAndCategory( channel[0], category[0] )

	def Exit( self ):
		self.conn.close()
		self.notice( "Exit" )
		pass


# -- Main Code ----------------------------------------------
addon = MediathekView()
addon.Init()
addon.Do()
addon.Exit()
del addon