import random, string, redis_bus
from uuid import uuid4
bus = redis_bus.Bus('sample_playground', prefix='random_')

@bus.register()
def uuid():
    return uuid4().get_hex()

@bus.register()
def password(length=12):
    return ''.join(random.choice(string.ascii_letters) for _ in range(length))
