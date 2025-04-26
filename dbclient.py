# -*- coding: utf-8 -*-

# @Author  : wzdnzd
# @Time    : 2025-04-25

import time

from pymysql.converters import escape_string

import utils
from connpool import get_instance
from logger import logger
from subscribe import SubscribeDetail


class MySQLClient(object):
    def __init__(self):
        # Get connection from the connection pool
        self.db = get_instance()

    def execute(self, sql, param=None, autoclose=False, retry=3):
        """Execute SQL statement"""
        count, retry = 0, max(0, retry)

        # Get connection from the connection pool
        conn, cursor = self.db.getconn()
        try:
            if param:
                count = cursor.execute(sql, param)
            else:
                count = cursor.execute(sql)

            conn.commit()
            if autoclose:
                self.close(conn, cursor)
        except Exception as e:
            logger.error(f"SQL execution error: {e}")
            logger.error(f"SQL: {sql}")
            if param:
                logger.error(f"Parameters: {param}")

            if retry > 0:
                conn.rollback()
                self.close(conn, cursor)
                return self.execute(sql, param, autoclose, retry - 1)

        return conn, cursor, count

    def close(self, conn, cursor):
        """Release connection back to the connection pool"""
        if cursor:
            cursor.close()

        if conn:
            conn.close()

    def __select(self, sql, param=None, all=False):
        """Query data from database"""
        conn, cursor = None, None

        try:
            conn, cursor, _ = self.execute(sql, param)
            result = cursor.fetchall() if all else cursor.fetchone()
            self.close(conn, cursor)
            return result
        except Exception as e:
            logger.error(e)
            self.close(conn, cursor)
            return None

    def selectone(self, sql, param=None):
        """Query a single record"""
        return self.__select(sql, param, False)

    def selectall(self, sql, param=None):
        """Query all records"""
        return self.__select(sql, param, True)

    def insertmany(self, sql, param, retry=3):
        """Insert multiple records"""
        conn, cursor = self.db.getconn()
        count, retry = -1, max(0, retry)

        try:
            cursor.executemany(sql, param)
            conn.commit()
        except Exception as e:
            logger.error(e)
            conn.rollback()

        self.close(conn, cursor)
        return count

    def update(self, sql, param=None):
        """Update records"""
        conn, cursor, count = None, None, -1

        try:
            conn, cursor, count = self.execute(sql, param)
            conn.commit()
        except Exception as e:
            logger.error(e)
            conn.rollback()

        self.close(conn, cursor)
        return count

    def insertone(self, sql, param):
        """Insert a single record"""
        return self.update(sql, param)

    def delete(self, sql, param=None):
        """Delete records"""
        return self.update(sql, param)

    def create(self, table, sql, overwrite=False):
        """Create table"""
        table, success = utils.trim(table), False
        if not table:
            logger.error("Failed to create table, table name cannot be empty")
            return success

        conn, cursor = self.db.getconn()
        try:
            if overwrite:
                cursor.execute(f"DROP TABLE IF EXISTS {table}")

            cursor.execute(sql)
            conn.commit()
            success = True
        except Exception as e:
            logger.error(e)
            conn.rollback()
            success = False

        self.close(conn, cursor)
        return success


@utils.singleton
def get_client():
    return MySQLClient()


def create_table(table: str) -> bool:
    """Create table if it doesn't exist"""
    table = utils.trim(table)
    if not table:
        logger.error("Failed to create table, table name cannot be empty")
        return False

    sql = f"""
        CREATE TABLE IF NOT EXISTS `{table}` (
            `id` int NOT NULL AUTO_INCREMENT COMMENT 'Primary key',
            `target` varchar(50) NOT NULL COMMENT 'Target type: clash, v2ray, mixed, singbox, loon, surge, quanx',
            `content` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT 'Subscribe content',
            `without_rules` tinyint(1) NOT NULL DEFAULT '0' COMMENT 'Whether to remove rules: 0-with rules, 1-without rules',
            `partition` int NOT NULL DEFAULT '1' COMMENT 'Partition number',
            `created_at` bigint NOT NULL DEFAULT (UNIX_TIMESTAMP()) COMMENT 'Created time (unix timestamp)',
            `updated_at` bigint NOT NULL DEFAULT (UNIX_TIMESTAMP()) COMMENT 'Updated time (unix timestamp)',
            PRIMARY KEY (`id` DESC),
            UNIQUE KEY `uk_target_without_rules_partition` (`target`, `without_rules`, `partition`),
            KEY `idx_target` (`target`),
            KEY `idx_target_without_rules` (`target`, `without_rules`),
            KEY `idx_created_at` (`created_at`),
            KEY `idx_updated_at` (`updated_at`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
    """

    return get_client().create(table, sql, False)


def check_subscribe_exists(table: str, target: str, without_rules: bool, partition: int) -> bool:
    """Check if a subscribe record with the given target, without_rules, and partition exists"""
    table = utils.trim(table)
    if not table:
        logger.error("Failed to check subscribe existence, table name cannot be empty")
        return False

    target = utils.trim(target)
    if not target:
        logger.error("Failed to check subscribe existence, target cannot be empty")
        return False

    # Escape strings to prevent SQL injection
    target = escape_string(target)
    without_rules_val = 1 if without_rules else 0

    sql = f"""
        SELECT COUNT(*) as count FROM `{table}`
        WHERE `target` = '{target}'
        AND `without_rules` = {without_rules_val}
        AND `partition` = {partition}
    """

    try:
        result = get_client().selectone(sql)
        if not result:
            return False
        # Handle both tuple and dictionary results
        if isinstance(result, dict):
            return result["count"] > 0
        elif isinstance(result, tuple):
            return result[0] > 0
        else:
            return False
    except Exception as e:
        logger.error(f"Failed to check subscribe existence: {e}")
        return False


def insert_subscribe(table: str, info: SubscribeDetail, update_if_exists: bool = True) -> bool:
    """
    Insert subscribe information into the database

    Args:
        table: Table name
        info: Subscribe information
        update_if_exists: Whether to update the record if it already exists

    Returns:
        bool: Whether the operation was successful
    """
    table = utils.trim(table)
    if not table:
        logger.error("Failed to insert subscribe info, table name cannot be empty")
        return False

    if not info or not isinstance(info, SubscribeDetail):
        logger.error("Failed to insert subscribe info, info cannot be empty")
        return False

    # Escape strings to prevent SQL injection
    content = escape_string(info.content)
    if not content:
        logger.error("Failed to insert subscribe info, content cannot be empty")
        return False

    target = escape_string(utils.trim(info.target))
    if not target:
        logger.error("Failed to insert subscribe info, target cannot be empty")
        return False

    without_rules = 1 if info.without_rules else 0
    partition = info.partition

    # Use current timestamp if created_at or updated_at is not provided
    current_time = int(time.time())
    created_at = info.created_at if hasattr(info, "created_at") and info.created_at else current_time
    updated_at = info.updated_at if hasattr(info, "updated_at") and info.updated_at else current_time

    # Check if record already exists
    exists = check_subscribe_exists(table, target, bool(without_rules), partition)

    if exists:
        if update_if_exists:
            # Update existing record
            return update_subscribe(table, info, None)
        else:
            logger.info(
                f"Subscribe info already exists for target={target}, without_rules={without_rules}, partition={partition}"
            )
            return True

    # Insert new record
    sql = f"""
        INSERT INTO `{table}`
        (`target`, `content`, `without_rules`, `partition`, `created_at`, `updated_at`)
        VALUES (%s, %s, %s, %s, %s, %s)
    """

    try:
        # Use parameterized query to handle large content and special characters
        params = (target, info.content, without_rules, partition, created_at, updated_at)
        result = get_client().insertone(sql, params)
        return result > 0
    except Exception as e:
        logger.error(f"Failed to insert subscribe info: {e}")
        return False


def update_subscribe(table: str, info: SubscribeDetail, id: int = None) -> bool:
    """Update subscribe information in the database"""
    table = utils.trim(table)
    if not table:
        logger.error("Failed to update subscribe info, table name cannot be empty")
        return False

    if not info or not isinstance(info, SubscribeDetail):
        logger.error("Failed to update subscribe info, info cannot be empty")
        return False

    # Escape strings to prevent SQL injection
    content = escape_string(info.content)
    if not content:
        logger.error("Failed to update subscribe info, content cannot be empty")
        return False

    target = escape_string(utils.trim(info.target))
    without_rules = 1 if info.without_rules else 0
    partition = info.partition

    # Always use current time for updated_at when updating records
    updated_at = int(time.time())

    if id:
        # Update by ID
        sql = f"""
            UPDATE `{table}` SET
            `content` = %s,
            `updated_at` = %s
            WHERE `id` = %s
        """
        params = (info.content, updated_at, id)
    else:
        # If no ID is provided, update based on target, without_rules, and partition
        sql = f"""
            UPDATE `{table}` SET
            `content` = %s,
            `updated_at` = %s
            WHERE `target` = %s AND `without_rules` = %s AND `partition` = %s
        """
        params = (info.content, updated_at, target, without_rules, partition)

    try:
        result = get_client().update(sql, params)
        return result > 0
    except Exception as e:
        logger.error(f"Failed to update subscribe info: {e}")
        return False


def get_subscribe(table: str, target: str, without_rules: bool = False, partition: int = 1) -> SubscribeDetail:
    """Get subscribe information from the database"""
    table = utils.trim(table)
    if not table:
        logger.error("Failed to get subscribe info, table name cannot be empty")
        return None

    target = utils.trim(target)
    if not target:
        logger.error("Failed to get subscribe info, target cannot be empty")
        return None

    # Escape strings to prevent SQL injection
    target = escape_string(target)
    without_rules_val = 1 if without_rules else 0

    sql = f"""
        SELECT * FROM `{table}`
        WHERE `target` = '{target}'
        AND `without_rules` = {without_rules_val}
        AND `partition` = {partition}
        ORDER BY `updated_at` DESC
        LIMIT 1
    """

    try:
        result = get_client().selectone(sql)
        if not result:
            return None

        # Convert database row to SubscribeInfo object
        if isinstance(result, dict):
            return SubscribeDetail(
                target=result["target"],
                content=result["content"],
                without_rules=bool(result["without_rules"]),
                partition=result["partition"],
                created_at=result["created_at"],
                updated_at=result["updated_at"],
            )
        elif isinstance(result, tuple):
            # Assuming the order of columns in the SELECT statement matches the order of fields in the table
            # id, target, content, without_rules, partition, created_at, updated_at
            return SubscribeDetail(
                target=result[1],
                content=result[2],
                without_rules=bool(result[3]),
                partition=result[4],
                created_at=result[5],
                updated_at=result[6],
            )
    except Exception as e:
        logger.error(f"Failed to get subscribe info: {e}")
        return None


def get_all_subscribe(table: str, target: str = None, without_rules: bool = None) -> list[SubscribeDetail]:
    """Get all subscribe information from the database"""
    table = utils.trim(table)
    if not table:
        logger.error("Failed to get all subscribe info, table name cannot be empty")
        return []

    where_clauses = []
    if target:
        target = escape_string(utils.trim(target))
        where_clauses.append(f"`target` = '{target}'")

    if without_rules is not None:
        without_rules_val = 1 if without_rules else 0
        where_clauses.append(f"`without_rules` = {without_rules_val}")

    where_clause = ""
    if where_clauses:
        where_clause = "WHERE " + " AND ".join(where_clauses)

    sql = f"""
        SELECT * FROM `{table}`
        {where_clause}
        ORDER BY `target`, `without_rules`, `partition`, `updated_at` DESC
    """

    try:
        results = get_client().selectall(sql)
        if not results:
            return []

        # Convert database rows to SubscribeInfo objects
        subscribe_infos = []
        for result in results:
            if isinstance(result, dict):
                subscribe_infos.append(
                    SubscribeDetail(
                        target=result["target"],
                        content=result["content"],
                        without_rules=bool(result["without_rules"]),
                        partition=result["partition"],
                        created_at=result["created_at"],
                        updated_at=result["updated_at"],
                    )
                )
            elif isinstance(result, tuple):
                # Assuming the order of columns in the SELECT statement matches the order of fields in the table
                # id, target, content, without_rules, partition, created_at, updated_at
                subscribe_infos.append(
                    SubscribeDetail(
                        target=result[1],
                        content=result[2],
                        without_rules=bool(result[3]),
                        partition=result[4],
                        created_at=result[5],
                        updated_at=result[6],
                    )
                )
        return subscribe_infos
    except Exception as e:
        logger.error(f"Failed to get all subscribe info: {e}")
        return []


def delete_subscribe(
    table: str,
    id: int = None,
    target: str = None,
    without_rules: bool = None,
    partition: int = None,
):
    """Delete subscribe information from the database"""
    table = utils.trim(table)
    if not table:
        logger.error("Failed to delete subscribe info, table name cannot be empty")
        return False

    if not id and not target:
        logger.error("Failed to delete subscribe info, either id or target must be provided")
        return False

    where_clauses = []
    if id:
        where_clauses.append(f"`id` = {id}")
    else:
        target = escape_string(utils.trim(target))
        where_clauses.append(f"`target` = '{target}'")

        if without_rules is not None:
            without_rules_val = 1 if without_rules else 0
            where_clauses.append(f"`without_rules` = {without_rules_val}")

        if partition is not None:
            where_clauses.append(f"`partition` = {partition}")

    where_clause = "WHERE " + " AND ".join(where_clauses)

    sql = f"""
        DELETE FROM `{table}`
        {where_clause}
    """

    try:
        result = get_client().delete(sql, None)
        return result > 0
    except Exception as e:
        logger.error(f"Failed to delete subscribe info: {e}")
        return False


def delete_subscribe_expired(table: str, partition: int, target: str = None) -> bool:
    """Delete subscribe information from the database where partition is greater than the specified value"""
    table = utils.trim(table)
    if not table:
        logger.error("Failed to delete subscribe info, table name cannot be empty")
        return False

    if not partition:
        logger.error("Failed to delete subscribe info, partition cannot be empty")
        return False

    where_clauses = [f"`partition` > {partition}"]

    if target:
        target = escape_string(utils.trim(target))
        where_clauses.append(f"`target` = '{target}'")

    where_clause = "WHERE " + " AND ".join(where_clauses)

    sql = f"""
        DELETE FROM `{table}`
        {where_clause}
    """

    try:
        result = get_client().delete(sql, None)
        return result > 0
    except Exception as e:
        logger.error(f"Failed to delete subscribe info: {e}")
        return False
