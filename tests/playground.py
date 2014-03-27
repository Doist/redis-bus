from uuid import uuid4


def hello(username='world'):
    return u'Hello, %s' % username


def uuid(seed):
    """
    Return random uuid value

    :param seed: doesn't play any role in data-generating value, just used to
        make sure caching works as expected
    """
    return uuid4().get_hex()
