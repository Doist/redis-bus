# -*- coding: utf-8 -*-
import json
import redis
import uuid
import pickle
import fnmatch
from werkzeug.utils import import_string, validate_arguments, bind_arguments


unset = object()


class Bus(object):
    """
    Redis Bus main class

    The class contains all the functions to work with the bus. All other
    classes like :class:`Method` and :class:`AsyncResults`
    are no more than wrappers providing syntactic sugar for end-users.

    The bus has a name, which is used as a prefix for all keys in the database

    In the database itself following structure is maintained:

    - `prefix:endpoints`: SET with all known bus endpoints
    -
    """

    def __init__(self, name='redis_bus', conn=None, result_expire=3600,
                 cache_expire=3600 * 24, prefix=None, **redis_kwargs):
        """
        Init the bus

        :param name: Bus name (redis prefix)
        :param conn: Optional StrictRedis connection object
        :param result_expire: set up result expiration timeout (in seconds).
            None means "never expire"
        :param cache_expire: set up cache expiration timeout (in seconds).
            None means "never expire"
        :param prefix: default prefix, which will be added to all registered
            functions (poorman's namespace)
        :param \*\*redis_kwargs: Optional Redis keyword arguments to connect
            to Redis instance
        """
        self.name = name
        self.result_expire = result_expire
        self.cache_expire = cache_expire
        self.prefix = prefix
        self.serve_pattern = prefix + '*' if prefix else '*'
        if conn is not None:
            self.r = conn
        else:
            self.r = redis.StrictRedis(**redis_kwargs)

    def cleanup(self):
        """
        Remove all keys, created by the bus
        """
        keys = self.r.keys(self._k('*'))
        if keys:
            self.r.delete(*keys)

    def all_methods(self):
        """
        Return all methods names
        """
        return self.r.hkeys(self._k('methods'))

    def get_method(self, name):
        """
        Get the :class:`Method` object by object name

        Implementation details: it checks the `prefix:methods`
        which should be the hash containing method names as keys and
        json-encoded function parameters (full path to function name and
        the cache key if cache is used).
        """
        json_data = self.r.hget(self._k('methods'), name)
        if json_data:
            data = json.loads(json_data)
            return Method(self, func=data['fn'], name=name, cache_key=data['ck'])

    def register_method(self, func, name=None, cache_key=None):
        """
        Register a new method in the endpoint and return a :class:`Method` object.

        :param func: importable function object or full module path to it
        :param name: optional name of the method. If not set, the function name
            with optional prefix will be used
        :param cache_key: optional cache key template string. The template
            string is populated by function keyword arguments. Upon
            execution the function result is cached. The caller side before
            execution checks the cache, and if the value is found, use this
            value instead.
        """
        if callable(func):
            func = func.__module__ + '.' + func.__name__

        if name is None:
            name = func.rsplit('.', 1)[-1]
            if self.prefix:
                name = '%s%s' % (self.prefix, name)

        if func.startswith('__main__.'):
            raise RuntimeError('Unable to register method %r from the "main" module' % func)

        params = json.dumps({'fn': func, 'ck': cache_key})
        self.r.hset(self._k('methods'), name, params)
        return self.get_method(name)

    def register(self, name=None, cache_key=None):
        """
        Return a decorator to decorate functions

        :param name: method name to expose by the bus
        :param cache_key: optional cache key template
        """
        def register_decorator(func):
            self.register_method(func, name, cache_key)
            return func
        return register_decorator


    def run_method(self, method_name, args, kwargs, result_id):
        """
        Enqueue method for remote execution

        :param method_name: the name of the method (method must be previously
            registered in the endpoint with the :func:`register_method` call)
        :param args: execution args
        :param kwargs: execution kwargs
        :param result_id: the id the async result

        Implementation details:

        Caller search the method by name. If method
        supports caching, the cache template is populated by args and kwargs
        and search in cache is performed first. If the result is found,
        we create and return a pre-populated AsyncResult. The cached result
        is expected to be found in `prefix:cache:<method_name>:<cache_key>`

        Otherwise we enqueue the method (add it to the `prefix:calls:<method_name>` list)
        and return the async result. Async result expects to find results in
        the `prefix:results:<id>` key, and can block to wait.
        """
        # check the cache first
        method_opts = self._get_method_options(method_name)
        cached_result = self._check_cache(method_name, method_opts, args, kwargs)
        if cached_result is unset:
            self._enqueue_method(method_name, args, kwargs, result_id)
            return AsyncResult(result_id, self)
        else:
            return AsyncResult(result_id, self, cached_result)

    def clear_method_cache(self, method_name, args, kwargs):
        method_opts = self._get_method_options(method_name)
        redis_cache_key = self._get_redis_cache_key(method_name, method_opts, args, kwargs)
        if redis_cache_key:
            self.r.delete(redis_cache_key)

    def _get_method_options(self, method_name):
        """
        Return decoded method options as a dict by method name.

        Returned dict will contain following fields:

        - fn: full path to the function as a string
        - function: actual callable function
        - ck: cache key
        """
        json_method = self.r.hget(self._k('methods'), method_name)
        if not json_method:
            raise RuntimeError('%r is not known method' % json_method)
        method = self._decode_method_options(json_method)
        return method

    def _decode_method_options(self, data):
        """
        Helper function to decode method data and import string

        """
        method = json.loads(data)
        method['function'] = import_string(method['fn'])
        return method

    def _check_cache(self, method_name, method_opts, args, kwargs):
        """
        Internal function to check the cache contents. Returns unset() special
        object, if there is nothing in cache
        """
        redis_cache_key = self._get_redis_cache_key(method_name, method_opts, args, kwargs)
        if redis_cache_key is None:
            return unset

        if self.r.exists(redis_cache_key):
            return pickle.loads(self.r.get(redis_cache_key))

        return unset

    def _get_redis_cache_key(self, method_name, method_opts, args, kwargs):
        """
        Return redis cache key by method opts and function args and kwargs
        """
        cache_key = method_opts['ck']
        if cache_key is None:
            return None

        func = method_opts['function']
        bind_kwargs = bind_arguments(func, args[:], kwargs.copy())
        cache_key = cache_key.format(**bind_kwargs)
        return self._k('cache', method_name, cache_key)

    def _enqueue_method(self, method_name, args, kwargs, result_id):
        """
        Internal function to put the method in the queue
        """
        data = pickle.dumps([args, kwargs, result_id])
        self.r.lpush(self._k('calls', method_name), data)

    def serve_once(self, pattern=None):
        """
        Search for all call queues awaited to be executed. Execute everything
        and exit.
        """
        pattern = self.serve_pattern if pattern is None else pattern
        method_names = fnmatch.filter(self.all_methods(), pattern)
        for method_name in method_names:
            method_opts = self._get_method_options(method_name)
            while True:
                data = self.r.rpop(self._k('calls', method_name))
                if data is None:
                    break
                self._exec_function(method_name, data, method_opts)

    def serve(self, pattern=None):
        """
        Execute all enqueued call request in infinite loop
        """
        pattern = self.serve_pattern if pattern is None else pattern
        method_names = fnmatch.filter(self.all_methods(), pattern)
        print('Serving %s' % method_names)

        if not method_names:
            raise RuntimeError('Nothing to serve')

        all_method_opts = {m: self._get_method_options(m) for m in method_names}

        # keys we should watch
        keys = [self._k('calls', method_name) for method_name in method_names]

        # start watching
        while True:
            key, data = self.r.brpop(keys)
            method_name = key.rsplit(':', 1)[-1]
            method_opts = all_method_opts[method_name]
            self._exec_function(method_name, data, method_opts)

    def _get_methods(self, endpoint_name):
        methods = self.r.hgetall(self._k('methods', endpoint_name))
        ret = {}
        for key, json_params in methods.items():
            # params contains "fn" (function) and "ck" (cache key) attributes
            params = json.loads(json_params)
            params['function'] = import_string(params['fn'])
            ret[key] = params
        return ret

    def _exec_function(self, method_name, data, method_opts):
        """
        Execute a function by method name, pickle-encoded data and method options

        :param method_name: the string with a method name
        :param data: pickle-loaded data with arguments and result id
        :param method_opts: the dictionary which for every method name contains
            function object and a cache key (if defined)
        """
        args, kwargs, result_id = pickle.loads(data)
        func = method_opts['function']

        # check the cache first (just in case)
        result = self._check_cache(method_name, method_opts, args, kwargs)
        if result is unset:

            # nothing is found? execute the function
            try:
                e_args, e_kwargs = validate_arguments(func, args[:], kwargs.copy())
                result = func(*e_args, **e_kwargs)
            except Exception as e:
                result = e

            # cache the result if it should be cached
            redis_cache_key = self._get_redis_cache_key(method_name, method_opts, args, kwargs)
            if redis_cache_key is not None:
                self.r.set(redis_cache_key, pickle.dumps(result))
                if self.cache_expire is not None:
                    self.r.expire(redis_cache_key, self.cache_expire)

        # store the result where we were asked
        result_key = self._k('results', result_id)
        self.r.rpush(result_key, pickle.dumps(result))
        if self.result_expire is not None:
            self.r.expire(result_key, self.result_expire)

    def get_async_result(self, async_result_id):
        """
        Return the contents by async result id.

        The method blocks until the result appears
        """
        key = self._k('results', async_result_id)
        _, raw_result = self.r.blpop(key)
        self.r.rpush(key, raw_result)
        result = pickle.loads(raw_result)
        if isinstance(result, Exception):
            raise result
        return result

    def _k(self, *args):
        """ Get the key with the bus prefix"""
        ret = [self.name] + list(args)
        return ':'.join(ret)

    @property
    def __members__(self):
        return self.all_methods()


    def __getattr__(self, attr):
        method = self.get_method(attr)
        if not method:
            raise AttributeError('Method %r not found' % attr)
        return method

    def __getitem__(self, key):
        method = self.get_method(key)
        if not method:
            raise KeyError('Method %r not found' % key)
        return method

    def __eq__(self, other):
        if not isinstance(other, Bus):
            return False
        return self.name == other.name
        # TODO: we don't compare Redis arguments

    def __repr__(self):
        return '<Bus:%s>' % self.name


class Method(object):

    def __init__(self, bus, name, func, cache_key):
        self.bus = bus
        self.name = name
        self.func = func
        self.cache_key = cache_key

    def __repr__(self):
        return '<Method:%s()>' % self.name

    def clear_cache(self, *args, **kwargs):
        return self.bus.clear_method_cache(self.name, args, kwargs)

    def run(self, *args, **kwargs):
        """
        Return AsyncResult with function result
        """
        result_id = uuid.uuid4().get_hex()
        return self.bus.run_method(self.name, args, kwargs, result_id)

    def __call__(self, *args, **kwargs):
        async_result = self.run(*args, **kwargs)
        return async_result.get()


class AsyncResult(object):

    def __init__(self, _id, bus, result=unset):
        self.id = _id
        self.bus = bus
        self.result = result

    def get(self):
        if self.result is unset:
            self.result = self.bus.get_async_result(self.id)
        return self.result


def main():
    """
    Main "serve from commandline" function
    """
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--pattern', default=None, help='filter patterns')
    parser.add_argument('bus', help='Bus object to serve')

    args = parser.parse_args()
    bus = import_string(args.bus)
    bus.serve(args.pattern)


if __name__ == '__main__':
    main()
