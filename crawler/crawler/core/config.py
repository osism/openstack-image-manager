import yaml
from pathlib import Path


def config_read(name, msg="config"):
    path = Path(name)
    if not path.is_file():
        return None

    try:
        config = yaml.safe_load(Path(name).read_text())
    except PermissionError:
        print("ERROR: could not open config - please check file permissions")
        return None
    except yaml.YAMLError as error:
        print("ERROR: %s" % error)
        return None

    print("Successfully read %s from %s" % (msg, name))

    return config
