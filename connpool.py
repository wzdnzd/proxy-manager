# -*- coding: utf-8 -*-

# @Author  : wzdnzd
# @Time    : 2025-04-25

from dbutils.pooled_db import PooledDB

import settings
import utils


class MyConnectionPool(object):
    __pool = None

    def __verify__(self):
        """Verify if the database configuration is correct"""
        for item in [settings.DB_HOST, settings.DB_USERNAME, settings.DB_PASSWORD, settings.DB_DATABASE]:
            text = utils.trim(item)
            if not text:
                return False

        return isinstance(settings.DB_PORT, int) and settings.DB_PORT > 0 and settings.DB_PORT <= 65535

    def __enter__(self):
        """Create database connection 'conn' and cursor 'cursor'"""
        self.conn = self.__getconn()
        self.cursor = self.conn.cursor()

    def __getconn(self):
        """Create database connection pool"""
        if self.__pool is None:
            if not self.__verify__():
                raise ValueError("Database connection configuration error")

            self.__pool = PooledDB(
                host=utils.trim(settings.DB_HOST),
                port=settings.DB_PORT,
                user=utils.trim(settings.DB_USERNAME),
                passwd=utils.trim(settings.DB_PASSWORD),
                db=utils.trim(settings.DB_DATABASE),
                creator=settings.DB_CREATOR,
                mincached=settings.DB_MIN_CACHED,
                maxcached=settings.DB_MAX_CACHED,
                maxshared=settings.DB_MAX_SHARED,
                maxconnections=settings.DB_MAX_CONNECYIONS,
                blocking=settings.DB_BLOCKING,
                maxusage=settings.DB_MAX_USAGE,
                setsession=settings.DB_SET_SESSION,
                use_unicode=True,
                charset=settings.DB_CHARSET,
            )

        return self.__pool.connection()

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Release connection pool resources"""
        self.cursor.close()
        self.conn.close()

    def getconn(self):
        """Get a connection from the connection pool"""
        conn = self.__getconn()
        cursor = conn.cursor()
        return conn, cursor


@utils.singleton
def get_instance():
    return MyConnectionPool()
