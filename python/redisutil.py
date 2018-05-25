#!/usr/bin/python
# -*- coding: utf-8 -*-
""" Global Config file
"""

import logging
from redis import Redis


class FilePath:
    SLASH = '/'
    BACKSLASH = '\\'

def with_redis_status(func):
    """装饰器，包装返回结果和Redis 状态
    """
    def inner(*args, **kwargs):
        error = False
        result = None
        try:
            result = func(*args, **kwargs)
        except Exception as e:
            logging.error(str(e))
            error = True
            result = None

        return {
                'result': result,
                'error':  error
        }

    return inner

class RedisCache(object):
    _Connection_ = None
    _host = 'localhost'
    _port = 6379
    _db = 0

    def __call__(cls, *args, **kwargs):
        if not hasattr(cls, '_instance'):
            cls._instance = super(RedisCache, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self,
                 host = 'localhost',
                 port = 6379,
                 db   = 0,
                 pwd = None):
        if not RedisCache._Connection_ or self._host != host or\
                self._port != port or self._db != db:
            self._host = host
            self._port = port
            self._db = db
            RedisCache._Connection_ = Redis(
                host = host,
                port = port,
                db   = db,
                password = pwd)

    @with_redis_status
    def publish(self, queue_id, content):
        '''发布消息'''
        return RedisCache._Connection_.publish(queue_id, content)

    @with_redis_status
    def subscribe(self, queue_id, content):
        '''订阅消息'''
        return RedisCache._Connection_.subscribe(queue_id, content)

    @with_redis_status
    def add_task(self, queue_id, content):
        '''加入任务到任务队列'''
        return RedisCache._Connection_.lpush(queue_id, content)

    @with_redis_status
    def get_task(self, queue_id):
        '''从任务队列中取任务'''
        return RedisCache._Connection_.rpop(queue_id)

    @with_redis_status
    def task_len(self, queue_id):
        '''从任务队列中取任务数量'''
        return RedisCache._Connection_.llen(queue_id)

    @with_redis_status
    def hset(self, key, field, value, expire=None):
        res = RedisCache._Connection_.hset(key, field, value)
        if expire > 0:
            RedisCache._Connection_.expire(key, expire)
        return res

    @with_redis_status
    def hget(self, key, field):
        return RedisCache._Connection_.hget(key, field)

    @with_redis_status
    def hdel(self, key, field):
        return RedisCache._Connection_.hdel(key, field)

    @with_redis_status
    def hmset(self, key, fv_dict, expire=None):
        res = RedisCache._Connection_.hmset(key, fv_dict)
        if expire > 0:
            RedisCache._Connection_.expire(key, expire)
        return res

    @with_redis_status
    def hmget(self, key, fields):
        return RedisCache._Connection_.hmget(key, fields)

    @with_redis_status
    def hgetall(self, key):
        return RedisCache._Connection_.hgetall(key)

    @with_redis_status
    def add_key(self, key, value):
        return RedisCache._Connection_.set(key, value)

    @with_redis_status
    def add_exp_key(self, key, value, ex):
        "Expired in seconds"
        return RedisCache._Connection_.set(key, value, ex)

    @with_redis_status
    def get_key(self, key):
        return RedisCache._Connection_.get(key)

    @with_redis_status
    def lpush(self, name, *values):
        return RedisCache._Connection_.lpush(name, *values)
    
    @with_redis_status
    def rpop(self, name):
        return RedisCache._Connection_.rpop(name)
    
    @with_redis_status
    def incr(self, key):
        return RedisCache._Connection_.incr(key)
    
    @with_redis_status
    def get_incr(self, key):
        return RedisCache._Connection_.get(key)

RedisCacheIns = RedisCache()

if __name__ == '__main__':
    print(RedisCache().add_task('TEST_QUEUE', 'xxx'*1024).get('error'))
    print(RedisCache().get_task('TEST_QUEUE').get('result'))
