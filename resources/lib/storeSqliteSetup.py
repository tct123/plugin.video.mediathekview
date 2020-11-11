# -*- coding: utf-8 -*-
"""
The local SQlite database module

Copyright 2017-2019, Leo Moll
SPDX-License-Identifier: MIT
"""
# pylint: disable=too-many-lines,line-too-long

import resources.lib.appContext as appContext

class StoreSQLiteSetup(object):

    def __init__(self, dbCon):
        self.logger = appContext.MVLOGGER.get_new_logger('StoreSQLite')
        self.conn = dbCon
        self._setupScript = """
PRAGMA foreign_keys = false;

-- ----------------------------
--  Table structure for film
-- ----------------------------
DROP TABLE IF EXISTS "film";
CREATE TABLE "film" (
     "idhash" TEXT(32,0) NOT NULL PRIMARY KEY,
     "dtCreated" integer(11,0) NOT NULL DEFAULT 0,
     "touched" integer(1,0) NOT NULL DEFAULT 1,
     "channel" TEXT(32,0) NOT NULL COLLATE NOCASE,
     "showid" TEXT(8,0) NOT NULL,
     "showname" TEXT(128,0) NOT NULL COLLATE NOCASE,
     "title" TEXT(128,0) NOT NULL COLLATE NOCASE,
     "aired" integer(11,0),
     "duration" integer(11,0),
     "size" integer(11,0),
     "description" TEXT(1024,0) COLLATE NOCASE,
     "url_sub" TEXT(384,0),
     "url_video" TEXT(384,0),
     "url_video_sd" TEXT(384,0),
     "url_video_hd" TEXT(384,0)
);
                        
-- ----------------------------
--  Table structure for status
-- ----------------------------
DROP TABLE IF EXISTS "status";
CREATE TABLE "status" (
     "status" TEXT(32,0),
     "lastupdate" integer(11,0),
     "lastFullUpdate" integer(11,0),
     "filmupdate" integer(11,0),
     "version" integer(11,0)
);

INSERT INTO status (status, lastupdate, lastFullUpdate, filmupdate, version) values ('IDLE', 0, 0, 0, 3);

PRAGMA foreign_keys = true;
        """

    def setupDatabase(self):
        self.logger.info('Start DB setup')
        self.conn.getConnection().executescript(self._setupScript)
        self.logger.info('End DB setup')
