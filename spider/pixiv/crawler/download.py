#!/usr/bin/env python
# -*- coding: utf-8 -*-
import json
import os
import re
import time
import threadpool

import u_base.u_log as log
from spider.pixiv.mysql.db import session, Illustration, IllustrationTag, IllustrationImage, query_top_total_bookmarks
from spider.pixiv.pixiv_api import AppPixivAPI
from spider.pixiv.arrange.file_util import read_file_as_list

CONFIG = json.load(open(os.path.join(os.getcwd(), r'config\config.json')))
_USERNAME = CONFIG.get('username')
_PASSWORD = CONFIG.get('password')


# 下载指定地址的图片，可是指定的URL或者IllustrationImage对象
def download_task(pixiv_api, directory, url=None, illustration_image: IllustrationImage = None):
    save_file_name = None
    begin_time = time.time()

    if not os.path.exists(directory):
        # 递归创建文件夹
        log.info('create directory: {}'.format(directory))
        os.makedirs(directory)
    if url is None or illustration_image is not None:
        # 通过illustration_image下载
        illustration_tags = session.query(IllustrationTag)\
            .filter(IllustrationTag.illust_id == illustration_image.illust_id).all()
        url = illustration_image.image_url_origin
        basename = os.path.basename(url).split('.')
        tags = list()
        for illustration_tag in illustration_tags:
            if illustration_tag.name not in tags:
                tags.append(illustration_tag.name)
        # 过滤掉tag名称中的特殊字符，避免无法创建文件
        save_file_name = re.sub(r"[\\/?*<>|\":]+", '', '-'.join(tags))[0:150]
        save_file_name = str(basename[0]) + '-' + save_file_name + '.' + str(basename[1])

    log.info('begin download image. save file name: {}, download url: {}'.format(save_file_name, url))
    if os.path.isfile(os.path.join(directory, save_file_name)) \
            and os.path.getsize(os.path.join(directory, save_file_name)) >= 200:
        log.info('The illust has been downloaded. file_name: {}'.format(save_file_name))
        return
    try:
        pixiv_api.download(url, '', directory, replace=False, name=save_file_name)
    except (OSError, NameError):
        log.error("save error, try again.")
        pixiv_api.download(url, '', directory, replace=False, name=save_file_name)
    log.info('download image end. cast: {}, url: {}'.format(time.time() - begin_time, url))


# 使用线程池并行下载
def download_by_pool(directory, urls=None):
    # 创建文件夹
    if not os.path.exists(directory):
        os.makedirs(directory)
    pixiv_api = AppPixivAPI()
    pixiv_api.login(_USERNAME, _PASSWORD)
    log.info('begin download image, url size: ' + str(len(urls)))
    pool = threadpool.ThreadPool(8)
    params = map(lambda v: (None, {'pixiv_api': pixiv_api, 'directory': directory, 'url': v}), urls)
    task_list = threadpool.makeRequests(download_task, params)
    [pool.putRequest(task) for task in task_list]
    pool.wait()


# 通过pixiv_id下载图片，从本地数据查找URL，然后下载图片
def download_by_illustration_id(pixiv_api, directory: str, illustration_id: int):
    log.info('begin download illust by illustration_id: {}'.format(illustration_id))
    illustration: Illustration = session.query(Illustration).get(illustration_id)
    if illustration is None:
        log.error('The illustration is not exist. illustration_id: {}'.format(illustration_id))
        return
    illustration_images: [IllustrationImage] = session.query(IllustrationImage)\
        .filter(IllustrationImage.illust_id == illustration_id).all()
    if illustration_images is None or len(illustration_images) == 0:
        log.error('The illustration image is not exist. illustration_id: {}'.format(illustration_id))
        return
    if len(illustration_images) > 3:
        # 超过3幅的画，大多是漫画类型，先不管
        log.warn('The illustration images are more than 3. illustration_id: {}'.format(illustration_id))
        return

    # 按照收藏点赞人数分文件夹
    # directory += '/' + '-'.join(str(i) for i in get_10_20(illustration.total_bookmarks))

    # if illustration.r_18 is not None and illustration.r_18 == 1:
        # R18放在别的文件夹
        # directory += "/r-18"

    for illustration_image in illustration_images:
        if illustration_image.image_url_origin is None or illustration_image.image_url_origin == '':
            log.info('The illustration_image image_url_origin is none. illustration_id: {}'.format(illustration_id))
            continue
        # if illustration_image.process == 'DOWNLOADED':
        #     log.info('The illustration_image has been downloaded. illustration_id: {}'.format(illustration_id))
        #     continue
        log.info('begin process illust_id: {}, image_url: {}'
                 .format(illustration_image.illust_id, illustration_image.image_url_origin))
        download_task(pixiv_api, directory, illustration_image=illustration_image)
        illustration_image.process = 'DOWNLOADED'
        session.merge(illustration_image)
        session.commit()
        log.info('end process illust_id: {}'.format(illustration_image.illust_id))
    log.info('begin download illust by illustration_id: {}, illust image size: {}'
             .format(illustration_id, len(illustration_images)))


# 下载某个用户的图片，基于本地数据库
def download_by_user_id(save_directory, user_id: int, min_total_bookmarks=5000):
    log.info('begin download illust by user_id: {}'.format(user_id))
    pixiv_api = AppPixivAPI()
    pixiv_api.login(_USERNAME, _PASSWORD)
    illustrations: [Illustration] = session.query(Illustration)\
        .filter(Illustration.user_id == user_id)\
        .filter(Illustration.total_bookmarks >= min_total_bookmarks)\
        .order_by(Illustration.total_bookmarks.desc()).all()
    if illustrations is None or len(illustrations) <= 0:
        log.warn('The illustrations is empty. user_id: {}'.format(user_id))
        return
    log.info('The illustrations size is: {}'.format(len(illustrations)))
    for illustration in illustrations:
        download_by_illustration_id(pixiv_api, save_directory, illustration.id)
    log.info('end download illust by user_id: {}'.format(user_id))


# 下载某个tag标签的图片，基于本地数据库
def download_by_tag(save_directory, tag: str, min_total_bookmarks=5000):
    log.info('begin download illust by tag: {}'.format(tag))
    pixiv_api = AppPixivAPI()
    pixiv_api.login(_USERNAME, _PASSWORD)
    illustrations: [Illustration] = session.query(Illustration) \
        .filter(Illustration.id.in_(
            session.query(IllustrationTag.illust_id).filter(IllustrationTag.name == tag))) \
        .filter(Illustration.total_bookmarks >= min_total_bookmarks) \
        .order_by(Illustration.total_bookmarks.desc()).all()
    log.info('The illustration of tag: {} count is: {}'.format(tag, len(illustrations)))
    for illustration in illustrations:
        download_by_illustration_id(pixiv_api, save_directory, illustration.id)
    log.info('end download illust by tag: {}'.format(tag))


# 获取整数倍 2324 -> [2000, 3000]
def get_10_20(number: int):
    figure = 0
    remain = number
    while remain // 10 > 0:
        remain = remain // 10
        figure += 1
    return [remain * (10 ** figure), (remain + 1) * (10 ** figure)]


# 下载TOP收藏图片
def download_top():
    directory = r"result/illusts"
    pixiv_api = AppPixivAPI()
    pixiv_api.login(_USERNAME, _PASSWORD)
    top_illusts = query_top_total_bookmarks()
    log.info("download illusts top size: {}".format(len(top_illusts)))
    for top_illust in top_illusts:
        log.info("begin download illust: {}".format(top_illust))
        download_by_illustration_id(pixiv_api, directory, top_illust["id"])
        log.info('end download illust: {}'.format(top_illust))


# 从文件中读取P站图片下载地址（每一行一个URL），并从P站下载
def download_from_url_files(url_file_path, save_directory):
    # 创建文件夹
    if not os.path.exists(save_directory):
        os.makedirs(save_directory)
    pixiv_api = AppPixivAPI()
    pixiv_api.login(_USERNAME, _PASSWORD)
    url_list = read_file_as_list(url_file_path)
    log.info('begin download image, url size: ' + str(len(url_list)))
    index = 0
    for url in url_list:
        log.info('index: ' + str(index))
        download_task(pixiv_api, save_directory, url)
        index += 1


if __name__ == '__main__':
    # download_by_pool()
    tag = '四宮かぐや'
    download_by_tag(os.path.join(r'.\result\by-tag', tag), tag)
    # user_id = 792198  # 5323203
    # save_file = os.path.join(r'.\result\by-user', str(user_id))
    # download_by_user_id(save_file, user_id)
