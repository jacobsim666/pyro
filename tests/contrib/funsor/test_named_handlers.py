# Copyright Contributors to the Pyro project.
# SPDX-License-Identifier: Apache-2.0

from collections import OrderedDict
import logging

import pytest
import torch

import pyro.contrib.funsor
from pyro.contrib.funsor.handlers.named_messenger import NamedMessenger

from pyroapi import pyro, pyro_backend

try:
    import funsor
    from funsor.domains import bint, reals
    from funsor.tensor import Tensor
    funsor.set_backend("torch")
except ImportError:
    pytestmark = pytest.mark.skip(reason="funsor is not installed")

logger = logging.getLogger(__name__)


def test_iteration():

    def testing():
        for i in pyro.markov(range(5)):
            v1 = pyro.to_data(Tensor(torch.ones(2), OrderedDict([(str(i), bint(2))]), 'real'))
            v2 = pyro.to_data(Tensor(torch.zeros(2), OrderedDict([('a', bint(2))]), 'real'))
            fv1 = pyro.to_funsor(v1, reals())
            fv2 = pyro.to_funsor(v2, reals())
            print(i, v1.shape)  # shapes should alternate
            if i % 2 == 0:
                assert v1.shape == (2,)
            else:
                assert v1.shape == (2, 1, 1)
            assert v2.shape == (2, 1)
            print(i, fv1.inputs)
            print('a', v2.shape)  # shapes should stay the same
            print('a', fv2.inputs)

    with pyro_backend("contrib.funsor"), NamedMessenger(first_available_dim=-1):
        testing()


def test_nesting():

    def testing():

        with pyro.markov():
            v1 = pyro.to_data(Tensor(torch.ones(2), OrderedDict([(str(1), bint(2))]), 'real'))
            print(1, v1.shape)  # shapes should alternate
            assert v1.shape == (2,)

            with pyro.markov():
                v2 = pyro.to_data(Tensor(torch.ones(2), OrderedDict([(str(2), bint(2))]), 'real'))
                print(2, v2.shape)  # shapes should alternate
                assert v2.shape == (2, 1)

                with pyro.markov():
                    v3 = pyro.to_data(Tensor(torch.ones(2), OrderedDict([(str(3), bint(2))]), 'real'))
                    print(3, v3.shape)  # shapes should alternate
                    assert v3.shape == (2,)

                    with pyro.markov():
                        v4 = pyro.to_data(Tensor(torch.ones(2), OrderedDict([(str(4), bint(2))]), 'real'))
                        print(4, v4.shape)  # shapes should alternate

                        assert v4.shape == (2, 1)

    with pyro_backend("contrib.funsor"), NamedMessenger(first_available_dim=-1):
        testing()


def test_staggered():

    def testing():
        for i in pyro.markov(range(12)):
            if i % 4 == 0:
                v2 = pyro.to_data(Tensor(torch.zeros(2), OrderedDict([('a', bint(2))]), 'real'))
                fv2 = pyro.to_funsor(v2, reals())
                assert v2.shape == (2,)
                print('a', v2.shape)
                print('a', fv2.inputs)

    with pyro_backend("contrib.funsor"), NamedMessenger(first_available_dim=-1):
        testing()


def test_fresh_inputs_to_funsor():

    def testing():
        x = pyro.to_funsor(torch.tensor([0., 1.]), funsor.reals(), dim_to_name={-1: "x"})
        assert set(x.inputs) == {"x"}
        px = pyro.to_funsor(torch.ones(2, 3), funsor.reals(), dim_to_name={-2: "x", -1: "y"})
        assert px.inputs["x"].dtype == 2 and px.inputs["y"].dtype == 3

    with pyro_backend("contrib.funsor"), NamedMessenger():
        testing()


def test_iteration_fresh():

    def testing():
        for i in pyro.markov(range(5)):
            fv1 = pyro.to_funsor(torch.zeros(2), reals(), dim_to_name={-1: str(i)})
            fv2 = pyro.to_funsor(torch.ones(2), reals(), dim_to_name={-1: "a"})
            v1 = pyro.to_data(fv1)
            v2 = pyro.to_data(fv2)
            print(i, v1.shape)  # shapes should alternate
            if i % 2 == 0:
                assert v1.shape == (2,)
            else:
                assert v1.shape == (2, 1, 1)
            assert v2.shape == (2, 1)
            print(i, fv1.inputs)
            print('a', v2.shape)  # shapes should stay the same
            print('a', fv2.inputs)

    with pyro_backend("contrib.funsor"), NamedMessenger(first_available_dim=-1):
        testing()


def test_staggered_fresh():

    def testing():
        for i in pyro.markov(range(12)):
            if i % 4 == 0:
                fv2 = pyro.to_funsor(torch.zeros(2), reals(), dim_to_name={-1: 'a'})
                v2 = pyro.to_data(fv2)
                assert v2.shape == (2,)
                print('a', v2.shape)
                print('a', fv2.inputs)

    with pyro_backend("contrib.funsor"), NamedMessenger(first_available_dim=-1):
        testing()
