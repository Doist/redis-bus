import pytest
import multiprocessing
import redis_bus
import playground


#--- Fixtures

@pytest.yield_fixture
def bus():
    """ The bus we make changes in """
    bus = redis_bus.Bus('test_bus')
    yield bus
    bus.cleanup()


def _serve(bus):
    return bus.serve()


@pytest.yield_fixture
def worker(bus):
    """
    A worker which serves endpoint.

    Don't forget to run worker.start() after bus setup
    """
    p = multiprocessing.Process(target=_serve, args=(bus, ))
    yield p
    p.terminate()


def test_register_method(bus):
    bus.register_method(playground.hello)
    bus.register_method(playground.hello, name='hello_alias')
    assert isinstance(bus.hello, redis_bus.Method)
    assert isinstance(bus.hello_alias, redis_bus.Method)


def test_remote_calls(bus):
    bus.register_method(playground.hello, name='hello')

    result1 = bus.hello.run()
    result2 = bus.hello.run('Joe')
    result3 = bus.hello.run(username='Joe')

    bus.serve_once()

    assert result1.get() == 'Hello, world'
    assert result2.get() == 'Hello, Joe'
    assert result3.get() == 'Hello, Joe'


def test_cache(bus):
    bus.register_method(playground.uuid, cache_key='{seed}')

    value = bus.uuid.run(1)
    bus.serve_once()

    same_value = bus.uuid.run(1)  # cache hit
    another_value = bus.uuid.run(2)  # cache miss
    bus.serve_once()

    assert value.get() == same_value.get()
    assert value.get() != another_value.get()

    # clear the cache
    bus.uuid.clear_cache(1)
    third_value = bus.uuid.run(1)  # cache miss
    bus.serve_once()

    assert third_value.get() != value.get()


def test_serve(bus, worker):
    bus.register_method(playground.hello)
    worker.start()
    assert bus.hello() == 'Hello, world'


def test_cache_expire(bus):
    bus.cache_expire = 0
    bus.register_method(playground.uuid, cache_key='{seed}')

    value1 = bus.uuid.run(1)
    bus.serve_once()
    value1 = value1.get()

    value2 = bus.uuid.run(1)  # cache miss due to cache expiration
    bus.serve_once()
    value2 = value2.get()

    assert value1 != value2
