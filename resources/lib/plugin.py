# -*- coding: utf-8 -*-
"""
The plugin module

Copyright 2017-2018, Leo Moll and Dominik Schlösser
SPDX-License-Identifier: MIT
"""

# -- Imports ------------------------------------------------
from __future__ import unicode_literals  # ,absolute_import, division
# from future import standard_library
# from builtins import *
# standard_library.install_aliases()
import os
import time
from datetime import datetime

# pylint: disable=import-error
import xbmcgui
import xbmcplugin

from resources.lib.kodi.kodiaddon import KodiPlugin

from resources.lib.storeMySql import StoreMySQL
from resources.lib.storeSqlite import StoreSQLite
from resources.lib.notifierKodi import NotifierKodi
from resources.lib.downloader import Downloader
from resources.lib.searches import RecentSearches
from resources.lib.extendedSearch import ExtendedSearch
import resources.lib.extendedSearchModel as ExtendedSearchModel
import resources.lib.ui.livestreamUi as LivestreamUi
import resources.lib.ui.channelUi as ChannelUi
import resources.lib.ui.showUi as ShowUi
import resources.lib.ui.letterUi as LetterUi
import resources.lib.ui.filmlistUi as FilmlistUi


import resources.lib.appContext as appContext

# -- Classes ------------------------------------------------


class MediathekViewPlugin(KodiPlugin):
    """ The main plugin class """

    def __init__(self):
        super(MediathekViewPlugin, self).__init__()
        self.settings = appContext.MVSETTINGS
        self.notifier = appContext.MVNOTIFIER
        self.logger = appContext.MVLOGGER.get_new_logger('MediathekViewPlugin')
        if self.settings.getDatabaseType() == 0:
            self.logger.debug('Database driver: Internal (sqlite)')
            self.database = StoreSQLite()
        elif self.settings.getDatabaseType() == 1:
            self.logger.debug('Database driver: External (mysql)')
            self.database = StoreMySQL()
        else:
            self.logger.warn('Unknown Database driver selected')
            self.database = None
        ##
        ##self.database = Store()

    def show_main_menu(self):
        """ Creates the main menu of the plugin """
        xbmcplugin.setContent(self.addon_handle, '')
        # quick search
        self.add_folder_item(
            30901,
            {'mode': "search"},
            icon=os.path.join(self.path, 'resources', 'icons', 'search-m.png')
        )
        # search
        self.add_folder_item(
            30902,
            {'mode': "extendedSearchScreen", 'extendedSearchAction': 'SHOW'},
            icon=os.path.join(self.path, 'resources', 'icons', 'search-m.png')
        )
        # Browse livestreams
        self.add_folder_item(
            30903,
            {'mode': "livestreams"},
            icon=os.path.join(self.path, 'resources', 'icons', 'live2-m.png')
        )
        # Browse recently added
        self.add_folder_item(
            30904,
            {'mode': "recent", 'channel': ""},
            icon=os.path.join(self.path, 'resources', 'icons', 'new-m.png')
        )
        # Browse recently added by channel
        self.add_folder_item(
            30905,
            {'mode': "recentchannels"},
            icon=os.path.join(self.path, 'resources', 'icons', 'new-m.png')
        )
        # Browse by Initial->Show
        self.add_folder_item(
            30906,
            {'mode': "initial", 'channel': ""},
            icon=os.path.join(self.path, 'resources', 'icons', 'movie-m.png')
        )
        # Browse by Channel->Initial->Shows
        self.add_folder_item(
            30907,
            {'mode': "channels"},
            icon=os.path.join(self.path, 'resources', 'icons', 'movie-m.png')
        )
        # Database Information
        self.add_action_item(
            30908,
            {'mode': "action-dbinfo"},
            icon=os.path.join(self.path, 'resources', 'icons', 'dbinfo-m.png')
        )
        # Manual database update
        if self.settings.getDatabaseUpateMode() == 1 or self.settings.getDatabaseUpateMode() == 2:
            self.add_action_item(30909, {'mode': "action-dbupdate"})
        self.end_of_directory()
        self._check_outdate()
        self.run_builtin('Container.SetViewMode(55)')
        window = xbmcgui.Window(xbmcgui.getCurrentWindowId())
        viewid = window.getFocusId()
        self.logger.debug(" View id {}", viewid)

    def show_searches(self):
        """
        Fill the search screen with "New Search..." and the
        list of recent searches
        """
        xbmcplugin.setContent(self.addon_handle, '')
        self.add_folder_item(
            30931,
            {'mode': "newsearch"},
            icon=os.path.join(self.path, 'resources', 'icons', 'search-m.png')
        )
        RecentSearches(self).load().populate()
        self.end_of_directory()

    def new_search(self):
        """
        Asks the user to enter his search terms and then
        performs the search and displays the results.
        """
        settingid = 'lastsearch1'
        headingid = 30901
        # are we returning from playback ?
        search = self.get_setting(settingid)
        if search:
            # restore previous search
            ui = FilmlistUi.FilmlistUi(self)
            ui.generate(self.database.getQuickSearch(search))
        else:
            # enter search term
            (search, confirmed) = self.notifier.get_entered_text('', headingid)
            if len(search) > 2 and confirmed is True:
                RecentSearches(self).load().add(search).save()
                #
                ui = FilmlistUi.FilmlistUi(self)
                rs = self.database.getQuickSearch(search)
                ui.generate(rs)
                if len(rs) > 0:
                    self.set_setting(settingid, search)
            else:
                # pylint: disable=line-too-long
                self.logger.debug(
                    'The following ERROR can be ignored. It is caused by the architecture of the Kodi Plugin Engine')
                self.end_of_directory(False, cache_to_disc=True)

    def show_db_info(self):
        """ Displays current information about the database """
        info = self.database.get_status()
        heading = self.language(30908)
        infostr = self.language({
            'NONE': 30941,
            'UNINIT': 30942,
            'IDLE': 30943,
            'UPDATING': 30944,
            'ABORTED': 30945
        }.get(info['status'], 30941))
        infostr = self.language(30965) % infostr
        totinfo = self.language(30971) % (
            info['chn'],
            info['shw'],
            info['mov']
            )
        updinfo = self.language(30970) % (
            datetime.fromtimestamp(info['filmUpdate']).isoformat().replace('T',' '),
            datetime.fromtimestamp(info['lastFullUpdate']).isoformat().replace('T',' '),
            datetime.fromtimestamp(info['lastUpdate']).isoformat().replace('T',' ')
            )
        ##
        xbmcgui.Dialog().textviewer(
            heading,
            infostr + '\n\n' +
            totinfo + '\n\n' +
            updinfo
        )

    def _check_outdate(self, maxage=172800):
        if self.settings.getDatabaseUpateMode() != 1 and self.settings.getDatabaseUpateMode() != 2:
            # no check with update disabled or update automatic
            return
        if self.database is None:
            # should never happen
            self.notifier.show_outdated_unknown()
            return
        status = self.database.get_status()
        if status['status'] == 'NONE' or status['status'] == 'UNINIT':
            # should never happen
            self.notifier.show_outdated_unknown()
            return
        elif status['status'] == 'UPDATING':
            # great... we are updating. nuthin to show
            return
        # lets check how old we are
        tsnow = int(time.time())
        tsold = int(status['lastUpdate'])
        if tsnow - tsold > maxage:
            self.notifier.show_outdated_known(status)

    def init(self):
        """ Initialisation of the plugin """
        pass


    def run(self):
        """ Execution of the plugin """
        start = time.time()
        # save last activity timestamp
        self.settings.user_activity()
        # process operation
        self.logger.info("Plugin invoked with parameters {}", self.args)
        mode = self.get_arg('mode', None)
        if mode is None:
            self.show_main_menu()
        elif mode == 'search':
            self.show_searches()
        elif mode == 'newsearch':
            self.new_search()
        elif mode == 'research':
            search = self.get_arg('search', '')
            ui = FilmlistUi.FilmlistUi(self)
            ui.generate(self.database.getQuickSearch(search))
            RecentSearches(self).load().add(search).save()
            ###
        elif mode == 'delsearch':
            search = self.get_arg('search', '')
            RecentSearches(self).load().delete(search).save().populate()
            self.run_builtin('Container.Refresh')
            ##
        elif mode == 'extendedSearchScreen':
            ExtendedSearch(self, self.database, self.get_arg('extendedSearchAction', None), self.get_arg('searchId', None)).show()
            ##
        elif mode == 'livestreams':
            ui = LivestreamUi.LivestreamUi(self)
            ui.generate(self.database.getLivestreams())
            ##
        elif mode == 'recent':
            channel = self.get_arg('channel', "")
            channel == "" if channel == "0" else channel
            ui = FilmlistUi.FilmlistUi(self)
            ui.generate(self.database.getRecentFilms(channel))
            #self.database.get_recents(channel, FilmUI(self))
            ##
        elif mode == 'recentchannels':
            ui = ChannelUi.ChannelUi(self,'recent')
            ui.generate(self.database.getChannelsRecent())
        elif mode == 'channels':
            ui = ChannelUi.ChannelUi(self,'shows')
            ui.generate(self.database.getChannels())
        elif mode == 'action-dbinfo':
            self.run_builtin("ActivateWindow(busydialognocancel)")
            self.show_db_info()
            self.run_builtin("Dialog.Close(busydialognocancel)")            
        elif mode == 'action-dbupdate':
            self.settings.set_update_triggered('true')
            self.notifier.show_notification(30963, 30964)
        elif mode == 'initial':
            ui = LetterUi.LetterUi(self)
            ui.generate(self.database.getStartLettersOfShows())
        elif mode == 'shows':
            channel = self.get_arg('channel', "")
            channel == "" if channel == "0" else channel
            initial = self.get_arg('initial', "")
            initial == "" if initial == "0" else initial
            #self.database.get_shows(channel, initial, ShowUI(self))
            ui = ShowUi.ShowUi(self)
            if initial == "":
                ui.generate(self.database.getShowsByChannnel(channel))
            else:
                ui.generate(self.database.getShowsByLetter(initial))           
        elif mode == 'films':
            show = self.get_arg('show', "")
            show == "" if show == "0" else show
            channel = self.get_arg('channel', "")
            channel == "" if channel == "0" else channel
            #self.database.get_films(show, FilmUI(self))
            ui = FilmlistUi.FilmlistUi(self)
            ui.generate(self.database.getFilms(channel, show))
            ###
        elif mode == 'downloadmv':
            filmid = self.get_arg('id', "")
            quality = self.get_arg('quality', 1)
            Downloader(self).download_movie(filmid, quality)
        elif mode == 'downloadep':
            filmid = self.get_arg('id', "")
            quality = self.get_arg('quality', 1)
            Downloader(self).download_episode(filmid, quality)
        elif mode == 'playwithsrt':
            filmid = self.get_arg('id', "")
            Downloader(self).play_movie_with_subs(filmid)

        # cleanup saved searches
        if mode is None or mode != 'newsearch':
            self.set_setting('lastsearch1', '')
            self.set_setting('lastsearch2', '')
        ##
        self.logger.info('request processed: {} sec', time.time() - start)

    def exit(self):
        """ Shutdown of the application """
        self.database.exit()
