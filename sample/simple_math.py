import datetime, redis_bus
bus = redis_bus.Bus('sample_playground', prefix='math_')

@bus.register(cache_key='{a}/{b}')
def sum(a, b):
    return a + b

@bus.register(cache_key='{seed}')
def now(seed):
    return datetime.datetime.now()
