# Copyright Contributors to the Pyro project.
# SPDX-License-Identifier: Apache-2.0

from collections import OrderedDict
from contextlib import ExitStack

from pyro.poutine.reentrant_messenger import ReentrantMessenger

from pyro.contrib.funsor.handlers.runtime import _DIM_STACK, DimRequest, DimType, NameRequest, StackFrame


class DimStackCleanupMessenger(ReentrantMessenger):

    def __init__(self):
        self._saved_dims = ()
        return super().__init__()

    def __enter__(self):
        if self._ref_count == 0 and _DIM_STACK.outermost is None:
            _DIM_STACK.outermost = self
            for name, dim in self._saved_dims:
                _DIM_STACK.global_frame.write(name, dim)
            self._saved_dims = ()
        return super().__enter__()

    def __exit__(self, *args, **kwargs):
        if self._ref_count == 1 and _DIM_STACK.outermost is self:
            _DIM_STACK.outermost = None
            _DIM_STACK.set_first_available_dim(-1)
            for name, dim in reversed(tuple(_DIM_STACK.global_frame.name_to_dim.items())):
                self._saved_dims += (_DIM_STACK.global_frame.free(name, dim),)
        return super().__exit__(*args, **kwargs)


class NamedMessenger(DimStackCleanupMessenger):

    @staticmethod  # only depends on the global _DIM_STACK state, not self
    def _pyro_to_data(msg):

        funsor_value, = msg["args"]
        name_to_dim = msg["kwargs"].setdefault("name_to_dim", OrderedDict())
        dim_type = msg["kwargs"].setdefault("dim_type", DimType.LOCAL)

        batch_names = tuple(funsor_value.inputs.keys())

        # TODO implement this
        # check that name_to_dim is either completely specified or completely empty
        if len(name_to_dim) > 0 and frozenset(batch_names) != frozenset(name_to_dim):
            raise NotImplementedError("partially specified name_to_dim not supported")

        # interpret all names/dims as requests since we only run this function once
        for name in batch_names:
            dim = name_to_dim.get(name, None)
            name_to_dim[name] = _DIM_STACK.request(
                name, dim if isinstance(dim, DimRequest) else DimRequest(dim, dim_type))[1]

        msg["stop"] = True  # only need to run this once per to_data call

    @staticmethod  # only depends on the global _DIM_STACK state, not self
    def _pyro_to_funsor(msg):

        if len(msg["args"]) == 2:
            raw_value, output = msg["args"]
        else:
            raw_value = msg["args"][0]
            output = msg["kwargs"].setdefault("output", None)
        dim_to_name = msg["kwargs"].setdefault("dim_to_name", OrderedDict())
        dim_type = msg["kwargs"].setdefault("dim_type", DimType.LOCAL)

        event_dim = len(output.shape) if output else 0
        try:
            batch_shape = raw_value.batch_shape  # TODO make make this more robust
        except AttributeError:
            full_shape = getattr(raw_value, "shape", ())
            batch_shape = full_shape[:len(full_shape) - event_dim]

        batch_dims = tuple(dim for dim in range(-len(batch_shape), 0) if batch_shape[dim] > 1)

        # TODO implement this
        # check that dim_to_name is either completely specified or completely empty
        if len(dim_to_name) > 0 and frozenset(batch_dims) != frozenset(dim_to_name):
            raise NotImplementedError("partially specified dim_to_name not supported")

        # interpret all names/dims as requests since we only run this function once
        for dim in batch_dims:
            name = dim_to_name.get(dim, None)
            dim_to_name[dim] = _DIM_STACK.request(
                name if isinstance(name, NameRequest) else NameRequest(name, dim_type), dim)[0]

        msg["stop"] = True  # only need to run this once per to_funsor call


class LocalNamedMessenger(NamedMessenger):
    """
    Handler for converting to/from funsors consistent with Pyro's positional batch dimensions.

    :param int history: The number of previous contexts visible from the
        current context. Defaults to 1. If zero, this is similar to
        :class:`pyro.plate`.
    :param bool keep: If true, frames are replayable. This is important
        when branching: if ``keep=True``, neighboring branches at the same
        level can depend on each other; if ``keep=False``, neighboring branches
        are independent (conditioned on their shared ancestors).
    """
    def __init__(self, history=1, keep=False):
        self.history = history
        self.keep = keep
        self._iterable = None
        self._saved_frames = []
        super().__init__()

    def __call__(self, fn):
        if fn is not None and not callable(fn):
            self._iterable = fn
            return self
        return super().__call__(fn)

    def __iter__(self):
        assert self._iterable is not None
        _DIM_STACK.iter_frame = _DIM_STACK.current_frame
        with ExitStack() as stack:
            for value in self._iterable:
                stack.enter_context(self)
                yield value

    def __enter__(self):
        if self.keep and self._saved_frames:
            frame = self._saved_frames.pop()
        else:
            frame = StackFrame(
                name_to_dim=OrderedDict(), dim_to_name=OrderedDict(),
                history=self.history, keep=self.keep,
            )

        _DIM_STACK.push(frame)
        return super().__enter__()

    def __exit__(self, *args, **kwargs):
        if self.keep:
            self._saved_frames.append(_DIM_STACK.pop())
        else:
            _DIM_STACK.pop()
        return super().__exit__(*args, **kwargs)


class GlobalNamedMessenger(NamedMessenger):

    def __init__(self):
        self._saved_globals = ()
        super().__init__()

    def __enter__(self):
        if self._ref_count == 0:
            for name, dim in self._saved_globals:
                _DIM_STACK.global_frame.write(name, dim)
            self._saved_globals = ()
        return super().__enter__()

    def __exit__(self, *args, **kwargs):
        if self._ref_count == 1:
            for name, dim in self._saved_globals:
                _DIM_STACK.global_frame.free(name, dim)
        return super().__exit__(*args, **kwargs)

    def _pyro_post_to_funsor(self, msg):
        if msg["kwargs"]["dim_type"] in (DimType.GLOBAL, DimType.VISIBLE):
            for name in msg["value"].inputs:
                self._saved_globals += ((name, _DIM_STACK.global_frame.name_to_dim[name]),)

    def _pyro_post_to_data(self, msg):
        if msg["kwargs"]["dim_type"] in (DimType.GLOBAL, DimType.VISIBLE):
            for name in msg["args"][0].inputs:
                self._saved_globals += ((name, _DIM_STACK.global_frame.name_to_dim[name]),)


class BaseEnumMessenger(NamedMessenger):
    """
    handles first_available_dim management, enum effects should inherit from this
    """
    def __init__(self, first_available_dim=None):
        assert first_available_dim is None or first_available_dim < 0, first_available_dim
        self.first_available_dim = first_available_dim
        super().__init__()

    def __enter__(self):
        if self._ref_count == 0 and self.first_available_dim is not None:
            self._prev_first_dim = _DIM_STACK.set_first_available_dim(self.first_available_dim)
        return super().__enter__()

    def __exit__(self, *args, **kwargs):
        if self._ref_count == 1 and self.first_available_dim is not None:
            _DIM_STACK.set_first_available_dim(self._prev_first_dim)
        return super().__exit__(*args, **kwargs)


class MarkovMessenger(LocalNamedMessenger):
    """
    LocalNamedMessenger is meant to be a drop-in replacement for pyro.markov.
    """
    pass
