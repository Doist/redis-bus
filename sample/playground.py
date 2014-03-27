#!/usr/bin/env python
import redis_bus
from IPython import embed
bus = redis_bus.Bus('sample_playground')
embed()
