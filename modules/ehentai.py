# coding:utf-8
"""E(x)hentai components."""
import os
import random
import re

import requests
from bs4 import BeautifulSoup

from modules import globj

_LOGIN_URL = 'https://forums.e-hentai.org/index.php'
_ACCOUNT_URL = 'https://e-hentai.org/home.php'
_EXHENTAI_URL = 'https://exhentai.org/'


def _ban_checker(html: BeautifulSoup):
    if not html.head and 'Your IP address has been' in html.body.p.string:
        raise globj.ValidationError(html.body.p.string)


def login(se, proxy: dict, uid: str, pw: str) -> bool:
    """Login and set cookies for exhentai."""
    try:
        with se.post(_LOGIN_URL,
                     params={'act': 'Login', 'CODE': '01'},
                     data={'CookieDate': '1', 'UserName': uid, 'PassWord': pw},
                     headers={'User-Agent': random.choice(globj.GlobalVar.user_agent)},
                     proxies=proxy,
                     timeout=5) as login_res:
            login_html = BeautifulSoup(login_res.text, 'lxml')
            se.cookies.update(login_res.cookies)  # Set cookies

        if login_html.head.title.string == 'Please stand by...':
            with se.get(_EXHENTAI_URL,
                        proxies=proxy,
                        headers={'User-Agent': random.choice(globj.GlobalVar.user_agent)},
                        timeout=5) as ex_res:
                ex_html = BeautifulSoup(ex_res.text, 'lxml')
                _ban_checker(ex_html)
                if ex_html.head.title.string == 'ExHentai.org':
                    se.cookies.update(ex_res.cookies)  # Set cookies for exhentai
                    return True
                else:
                    raise globj.ValidationError('Cannot get into exhentai.')
        elif login_html.head.title.string == 'Log In':
            raise globj.ValidationError('Incorrect username or password.')
        else:
            raise globj.ResponseError('Abnormal response.')

    except requests.Timeout:
        raise requests.Timeout('Timeout during login.')
    except (globj.ResponseError, AttributeError) as e:
        raise globj.ResponseError('Login:' + repr(e))
    except globj.ValidationError:
        raise


def account_info(se, proxy: dict) -> tuple:
    """Get download limitation(used/all)."""
    try:
        with se.get(_ACCOUNT_URL,
                    headers={'User-Agent': random.choice(globj.GlobalVar.user_agent)},
                    proxies=proxy,
                    timeout=5) as info_res:
            info_html = BeautifulSoup(info_res.text, 'lxml')
        _ban_checker(info_html)
        info_node = info_html.find('div', class_='homebox')
        if info_node:
            limit = info_node('strong')
            return limit[0].string, limit[1].string
        else:
            raise globj.ResponseError('Abnormal response.')
    except requests.Timeout:
        raise requests.Timeout('Timeout during fetching account info.')
    except globj.ResponseError as e:
        raise globj.ResponseError('Fetching account info:' + repr(e))


def information(se, proxy: dict, addr: str):
    """
    Fetch gallery information, include misc info and thumbnail.
    Args:
        se: Session instance.
        proxy: (Optional) The proxy used.
        addr: Gallery address.
    """
    re_thumb = re.compile(r'.*url\((.*)\).*')
    # TODO: address = addr + '/' if addr[-1] != '/' else addr  # When the end of gallery addr is not /
    try:
        with se.get(addr,
                    params={'inline_set': 'ts_m'},
                    headers={'User-Agent': random.choice(globj.GlobalVar.user_agent)},
                    proxies=proxy,
                    timeout=5) as gallery_res:
            gallery_html = BeautifulSoup(gallery_res.text, 'lxml')
        _ban_checker(gallery_html)
        name = gallery_html.find('h1', id='gj').string  # Japanese name is prior
        if not name:
            name = gallery_html.find('h1', id='gn').string
        misc = gallery_html.find_all('td', class_='gdt2')
        thumb = re_thumb.match(gallery_html.find('div', id='gd1').div['style']).group(1)
        if name and misc and thumb:
            return {
                'gid': addr.split('/')[-3],
                'name': name,
                'size': misc[4].string,
                'page': int(misc[5].string[:-6]),
                'thumb': thumb
            }
        else:
            raise globj.ResponseError('Abnormal response.')
    except requests.Timeout:
        raise requests.Timeout('Timeout during fetching gallery info.')
    except (AttributeError, globj.ResponseError) as e:
        raise globj.ResponseError('Fetching gallery info:' + repr(e))


def fetch_keys(se, proxy: dict, addr: str, info: dict) -> dict:
    """
    Fetch keys(imgkeys and showkey) from gallery.
    Args:
        se: Session instance.
        proxy: (Optional) The proxy used.
        addr: Gallery address.
        info: Information of the gallery.
    Return:
        A dictionary. {'page': imgkey, '0': showkey}
    """
    re_imgkey = re.compile(r'https://exhentai\.org/s/(\w{10})/\d*-(\d{1,4})')
    re_showkey = re.compile(r'[\S\s]*showkey="(\w{11})"[\S\s]*')
    pn = info['page'] // 40 + 1  # range(0) has no element
    keys = dict()
    try:
        for p in range(pn):
            with se.get(addr,
                        params={'inline_set': 'ts_m', 'p': p},
                        headers={'User-Agent': random.choice(globj.GlobalVar.user_agent)},
                        proxies=proxy,
                        timeout=5) as gallery_res:
                gallery_html = BeautifulSoup(gallery_res.text, 'lxml')
            _ban_checker(gallery_html)

            # Fetch imgkey from every picture
            pics = gallery_html.find_all('div', class_='gdtm')
            for item in pics:
                match = re_imgkey.match(item.a['href'])
                keys[match.group(2)] = match.group(1)

        # Fetch showkey from first picture
        showkey_url = '/'.join(['https://exhentai.org/s', keys['1'], info['gid'] + '-1'])
        with se.get(showkey_url,
                    headers={'User-Agent': random.choice(globj.GlobalVar.user_agent)},
                    proxies=proxy,
                    timeout=5) as showkey_res:
            showkey_html = BeautifulSoup(showkey_res.text, 'lxml')
        _ban_checker(showkey_html)
        keys['0'] = re_showkey.match(showkey_html('script')[1].string).group(1)
        return keys
    except requests.Timeout:
        raise requests.Timeout('Timeout during fetching keys.')
    except AttributeError as e:
        raise globj.ResponseError('Fetching gallery keys:' + repr(e))


def download(se, proxy: dict, info: dict, keys: dict, page: int, path: str, retry=False):
    """
    Download one picture.
    Args:
        se: Session instance.
        proxy: (Optional) The proxy used.
        info: Information of the gallery.
        keys: Keys include imgkeys and showkey.
        page: Page number.
        path: Save root path.
        retry: Overwrite image instead of skipping it.
    """
    try:
        with se.post(_EXHENTAI_URL + 'api.php',
                     json={'method': 'showpage',
                           'gid': int(info['gid']),
                           'page': page,
                           'imgkey': keys[str(page)],
                           'showkey': keys['0']},
                     headers={'User-Agent': random.choice(globj.GlobalVar.user_agent)},
                     proxies=proxy,
                     timeout=5) as dl_res:  # Fetch original url of picture
            dl_json = dl_res.json()
        if dl_json.get('error'):
            raise globj.ResponseError(dl_json['error'])
        elif dl_json.get('i7'):
            url_html = BeautifulSoup(dl_json['i7'], 'lxml')  # Origin image
            origin = url_html.a['href']
        else:
            url_html = BeautifulSoup(dl_json['i3'], 'lxml')  # Showing image is original
            origin = url_html.a.img['src']

        folder_path = os.path.join(path, info['name'])
        if not os.path.exists(folder_path):
            print('mkdir:', folder_path)
            os.makedirs(folder_path)
        with se.get(origin,
                    headers={'User-Agent': random.choice(globj.GlobalVar.user_agent)},
                    proxies=proxy,
                    stream=True,
                    timeout=5) as pic_res:
            name = os.path.split(pic_res.url)[-1].rstrip('?dl=1')  # Get file name from url
            real_path = os.path.join(folder_path, name)
            if not os.path.exists(real_path) or retry:  # If file exists or not retry, skip it
                print('Downloading:', real_path)
                with open(real_path, 'ab') as data:
                    for chunk in pic_res.iter_content():
                        data.write(chunk)
            else:
                print('Skip:', name)
    except requests.Timeout:
        raise requests.Timeout('Timeout during downloading.')
    except (KeyError, AttributeError, globj.ResponseError) as e:
        raise globj.ResponseError('Downloading:' + repr(e))


if __name__ == '__main__':
    pass
