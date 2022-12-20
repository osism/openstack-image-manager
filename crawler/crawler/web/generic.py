import requests
import validators

from email.utils import parsedate_to_datetime

# from pprint import pprint


def url_fetch_content(url):
    try:
        request = requests.get(url, allow_redirects=True)
    except requests.exceptions.HTTPError as errh:
        print("ERROR: HTTP error: " + repr(errh))
        return None
    except requests.exceptions.ConnectionError as errc:
        print("ERROR: could not connect to the API: " + repr(errc))
        return None
    except requests.exceptions.Timeout as errt:
        # is not hit when timeout - why?
        print("ERROR: timeout while connecting: " + repr(errt))
        return None
    except requests.exceptions.RequestException as err:
        print("ERROR: unknown error: " + repr(err))
        return None

    content = request.content.decode("utf-8")

    return content


def url_get_header(url):
    if not validators.url(url):
        print("ERROR: ", url, " is not a valid URL")
        return None

    try:
        request = requests.head(url, allow_redirects=True)
        # info.raise_for_status()
    except requests.exceptions.HTTPError as errh:
        print("ERROR: HTTP error: " + repr(errh))
        return None
    except requests.exceptions.ConnectionError as errc:
        print("ERROR: could not connect to the API: " + repr(errc))
        return None
    except requests.exceptions.Timeout as errt:
        # is not hit when timeout - why?
        print("ERROR: timeout while connecting: " + repr(errt))
        return None
    except requests.exceptions.RequestException as err:
        print("ERROR: unknown error: " + repr(err))
        return None

    if request.status_code == 404:
        return None

    return request


def url_get_last_modified(url):
    request = url_get_header(url)
    if request is None:
        return None

    last_modified_date = request.headers['Last-Modified']
    datestring = parsedate_to_datetime(last_modified_date).strftime("%Y-%m-%d")

    return datestring


def url_exists(url):
    request = url_get_header(url)

    if request is None:
        return False
    else:
        return True
