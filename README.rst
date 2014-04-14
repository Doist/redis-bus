Redis bus
==========

A Redis-based inter-service communication bus with autodiscovery and cache.

The bus is useful to organize internal API in applications based on
service-oriented architecture (this is when your company gets its profit from
tons of small services which send messages back and forth as crazy).

Python supported version
------------------------

It's been tested for python 2.7 only yet.


Usage example
-------------

The core object of the system is :class:`redis_bus.Bus`, where every service
should register its own methods.

Suppose you have two services, one of which is a random number generator
and generates unique ids and passwords for you, while another one is the
service with helps you with math and contains a bunch of mathematics functions.

That's how RNG module could look like (see :file:`sample/rng.py`).

.. code-block:: python

    import random, string, redis_bus
    from uuid import uuid4
    bus = redis_bus.Bus('sample_playground', prefix='random_')

    @bus.register()
    def uuid():
        return uuid4().get_hex()

    @bus.register()
    def password(length=12):
        return ''.join(random.choice(string.ascii_letters) for _ in range(length))


As you can see, we start the code by creating a bus object. We pick a name for
it, and a prefix. Bus instances with equal names share the same bus settings
(because actually bus settings are stored in the Redis database). Every bus
knows about services published (registered) by its counterparts.

The prefix attribute is a "poor man's namespace". When you define a bus prefix,
it means that if you register a function without a method name (see
`Bus.register` and `Bus.register_method` docstring), the function
will be exposed with as prefix + function_name. Additionally, if you start
:func:`bus.serve` without parameters, it will serve only methods with your
prefix.

As we have a prefix "random_", the following code will expose two bus methods:
`random_uuid` and `random_password`.

Let's start the service with the following command.

.. code-block:: console

    cd sample
    redis-bus rng.bus


Here the "rng" is the name of the module where we search for the bus instance,
and "bus" is the name of the instance itself.

If you have IPython installed, you may start the :file:`playground.py` script. It will
start the IPython console and create a ready-to-use bus instance for you. What's
especially cool is that the bus object does know about all exposed modules already! Try
`bus.random_<tab>` for autocomplete.

The bus creates a bunch of proxy methods just for you. Your session may look like
this.

.. code-block:: python

    In []: bus.random_uuid()
    Out[]: '34301a18fc3d4ec6a3ce59e83b947046'

    In []: bus.random_uuid()
    Out[]: '687793cbcd214a68a7dda3d9b8182ca6'

    In []: bus.random_password()
    Out[]: 'jjGVZajVwJUD'

    In []: bus.random_password(20)
    Out[]: 'nGgQeKvtrFJTLYHAlJzJ'



Playing with the cache
----------------------

There is another module, for mathematics (see :file:`sample/simple_math.py`).
Usually maths functions output depends on their input only, so we can safely
cache values.

.. code-block:: python

    import datetime, redis_bus
    bus = redis_bus.Bus('sample_playground', prefix='math_')

    @bus.register(cache_key='{a}/{b}')
    def sum(a, b):
        return a + b

    @bus.register(cache_key='{seed}')
    def now(seed):
        return datetime.datetime.now()


The cache key is a "new-style" format string which accepts function keyword
arguments.

Note that there is a function :func:`now` which is used to demonstrate the
power of the cache. The `seed` argument is not used by the function itself, and
also is there to show how the cache works.

Start the worker.

.. code-block:: console

    cd sample
    redis-bus simple_math.bus

And then switch to the console (note that the bus object "automagically" discovers
new methods). The bus caches the value for seed equal to 1, and it returns
the same object every time. The same function with another seed value 2 returns
something else.

.. code-block:: python

    In []: bus.math_now(1)
    Out[]: datetime.datetime(2014, 3, 27, 23, 26, 21, 340512)

    In []: bus.math_now(1)
    Out[]: datetime.datetime(2014, 3, 27, 23, 26, 21, 340512)

    In []: bus.math_now(2)
    Out[]: datetime.datetime(2014, 3, 27, 23, 26, 25, 97391)

You may cleanup the cache manually.

.. code-block:: python

    In []: bus.math_now.clear_cache(1)

    In []: bus.math_now(1)
    Out[]: datetime.datetime(2014, 3, 27, 23, 28, 28, 168701)


Debugging facilities
--------------------

As you start writing your workers, it's often convenient to drop to pdb on
exception. If you want it, use one of following calls:

.. code-block:: python

    >>> bus.serve(debug=True)
    >>> bus.serve_once(debug=True)

Or, if you start the bus from the console

.. code-block:: python

    $ redis-bus --debug simple_math.bus

Don't forget to turn this mode off in production. Otherwise your worker stalls
on the first exception.


Cleanup everything
-------------------

As you're done with your playground, you may clean up the redis instance
after yourself.

.. code-block:: python

    In []: bus.cleanup()

Please note that the function uses Redis `KEYS` function which may not be scalable.


That's it.
