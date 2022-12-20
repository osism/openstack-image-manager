import sys
import sqlite3
from pathlib import Path


def database_connect(name):
    path = Path(name)
    if path.is_file():
        try:
            connection = sqlite3.connect(name)
        except sqlite3.OperationalError as error:
            print("ERROR: %s" % error)
            return None
        return connection
    else:
        return None


def database_disconnect(connection):
    connection.close()


def database_initialize(name):
    path = Path(name)
    if path.is_file():
        print("WARNING: database %s already exists. Cowardly refusing action." % name)
    else:
        create_statement_file_path = Path("lib/initialize-image-catalog.sql")
        if create_statement_file_path.is_file():
            db_init_file = open("lib/initialize-image-catalog.sql")
            create_statement = db_init_file.read()
            db_init_file.close()
        else:
            raise SystemError("Template lib/initialize-image-catalog.sql not found")

        try:
            connection = sqlite3.connect(name)
        except sqlite3.OperationalError as error:
            print("ERROR: %s" % error)
        database_cursor = connection.cursor()
        try:
            database_cursor.execute(create_statement)
        except Exception as error:
            print('ERROR: create table failed with the following error "%s"' % error)

        connection.close()
        print("New database created under %s" % name)


def db_get_last_checksum(connection, distribution, release):
    try:
        database_cursor = connection.cursor()
        database_cursor.execute("SELECT checksum FROM image_catalog "
                                "WHERE distribution_name = '%s' "
                                "AND distribution_release = '%s' "
                                "ORDER BY id DESC LIMIT 1" % (distribution, release))
    except sqlite3.OperationalError as error:
        raise SystemError("SQLite error: %s" % error)

    row = database_cursor.fetchone()

    if row is None:
        # print("no previous entries found")
        last_checksum = "sha256:none"
    else:
        last_checksum = row[0]

    database_cursor.close()

    return last_checksum


def db_get_last_entry(connection, distribution, release):
    return db_get_release_versions(connection, distribution, release, 1)


def db_get_release_versions(connection, distribution, release, limit):
    try:
        database_cursor = connection.cursor()
        database_cursor.execute("SELECT name, release_date, version, distribution_name, "
                                "distribution_release, url, checksum FROM image_catalog "
                                "WHERE distribution_name = '%s' AND distribution_release = '%s' "
                                "ORDER BY id DESC LIMIT %d" % (distribution, release, limit))
    except sqlite3.OperationalError as error:
        print("SQLite error: %s" % error)
        sys.exit(1)
    row = database_cursor.fetchone()

    if row is not None:
        last_entry = {}
        last_entry['name'] = row[0]
        last_entry['release_date'] = row[1]
        last_entry['version'] = row[2]
        last_entry['distribution_name'] = row[3]
        last_entry['distribution_version'] = row[4]
        last_entry['url'] = row[5]
        last_entry['checksum'] = row[6]

    database_cursor.close()

    return last_entry


def read_version_from_catalog(connection, distribution, release, version):
    try:
        database_cursor = connection.cursor()
        database_cursor.execute("SELECT version,checksum,url,release_date "
                                "FROM (SELECT * FROM image_catalog "
                                "WHERE distribution_name = '%s' "
                                "AND distribution_release = '%s' "
                                "AND version ='%s' "
                                "ORDER BY id DESC LIMIT 1) "
                                "ORDER BY ID" % (distribution, release, version))
    except sqlite3.OperationalError as error:
        raise SystemError("SQLite error: %s" % error)

    image_catalog = {}
    image_catalog['versions'] = {}

    for image in database_cursor.fetchall():
        version = image[0]
        image_catalog['versions'][version] = {}
        image_catalog['versions'][version]['checksum'] = image[1]
        image_catalog['versions'][version]['url'] = image[2]
        image_catalog['versions'][version]['release_date'] = image[3]

    return image_catalog


def write_catalog_entry(connection, update):
    try:
        database_cursor = connection.cursor()
        database_cursor.execute("INSERT INTO image_catalog "
                                "(name, release_date, version, distribution_name, "
                                "distribution_release, url, checksum) "
                                "VALUES (?,?,?,?,?,?,?)",
                                (update['name'], update['release_date'], update['version'],
                                 update['distribution_name'], update['distribution_release'],
                                 update['url'], update['checksum']))
        connection.commit()
    except sqlite3.OperationalError as error:
        raise SystemError("SQLite error: %s" % error)

    database_cursor.close()

    return None


def update_catalog_entry(connection, update):
    try:
        database_cursor = connection.cursor()
        database_cursor.execute("UPDATE image_catalog set url=?, checksum=? "
                                "WHERE name=? AND version=?",
                                (update['url'], update['checksum'],
                                 update['name'], update['version']))
        connection.commit()
    except sqlite3.OperationalError as error:
        raise SystemError("SQLite error: %s" % error)

    database_cursor.close()

    return None


def write_or_update_catalog_entry(connection, update):
    existing_entry = read_version_from_catalog(connection, update['distribution_name'],
                                               update['distribution_release'], update['version'])

    if update['version'] in existing_entry['versions']:
        print("Updating version " + update['version'])
        return update_catalog_entry(connection, update)
    else:
        return write_catalog_entry(connection, update)


def read_release_from_catalog(connection, distribution, release):
    try:
        database_cursor = connection.cursor()
        database_cursor.execute("SELECT version,checksum,url,release_date "
                                "FROM (SELECT * FROM image_catalog "
                                "WHERE distribution_name = '%s' "
                                "AND distribution_release = '%s' "
                                "ORDER BY id DESC LIMIT 3) "
                                "ORDER BY ID" % (distribution, release))
    except sqlite3.OperationalError as error:
        raise SystemError("SQLite error: %s" % error)

    image_catalog = {}
    image_catalog['versions'] = {}

    for image in database_cursor.fetchall():
        version = image[0]
        image_catalog['versions'][version] = {}
        image_catalog['versions'][version]['checksum'] = image[1]
        image_catalog['versions'][version]['url'] = image[2]
        image_catalog['versions'][version]['release_date'] = image[3]

    return image_catalog
