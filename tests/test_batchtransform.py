#
# Copyright 2013 Quantopian, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from collections import deque
from copy import deepcopy
from datetime import datetime
from unittest import TestCase

import pytz
import numpy as np
import pandas as pd

from zipline.algorithm import TradingAlgorithm
from zipline.finance.trading import TradingEnvironment
from zipline.sources.data_source import DataSource
from zipline.test_algorithms import (
    BatchTransformAlgorithm,
    BatchTransformAlgorithmMinute,
)
from zipline.testing import setup_logger, teardown_logger
from zipline.transforms import batch_transform
import zipline.utils.factory as factory
from zipline.utils.tradingcalendar import trading_days


@batch_transform
def return_price(data):
    return data.price


class BatchTransformAlgorithmSetSid(TradingAlgorithm):
    def initialize(self, sids=None):
        self.history = []

        self.batch_transform = return_price(
            refresh_period=1,
            window_length=10,
            clean_nans=False,
            sids=sids,
            compute_only_full=False
        )

    def handle_data(self, data):
        self.history.append(
            deepcopy(self.batch_transform.handle_data(data)))


class DifferentSidSource(DataSource):
    def __init__(self):
        self.dates = pd.date_range('1990-01-01', periods=180, tz='utc')
        self.start = self.dates[0]
        self.end = self.dates[-1]
        self._raw_data = None
        self.sids = range(90)
        self.sid = 0
        self.trading_days = []

    @property
    def instance_hash(self):
        return '1234'

    @property
    def raw_data(self):
        if not self._raw_data:
            self._raw_data = self.raw_data_gen()
        return self._raw_data

    @property
    def mapping(self):
        return {
            'dt': (lambda x: x, 'dt'),
            'sid': (lambda x: x, 'sid'),
            'price': (float, 'price'),
            'volume': (int, 'volume'),
        }

    def raw_data_gen(self):
        # Create differente sid for each event
        for date in self.dates:
            if date not in trading_days:
                continue
            event = {'dt': date,
                     'sid': self.sid,
                     'price': self.sid,
                     'volume': self.sid}
            self.sid += 1
            self.trading_days.append(date)
            yield event


class TestChangeOfSids(TestCase):
    def setUp(self):
        self.sids = range(90)
        self.env = TradingEnvironment()
        self.env.write_data(equities_identifiers=self.sids)

        self.sim_params = factory.create_simulation_parameters(
            start=datetime(1990, 1, 1, tzinfo=pytz.utc),
            end=datetime(1990, 1, 8, tzinfo=pytz.utc),
            env=self.env,
        )

    def test_all_sids_passed(self):
        algo = BatchTransformAlgorithmSetSid(
            sim_params=self.sim_params,
            env=self.env,
        )
        source = DifferentSidSource()
        algo.run(source)
        for i, (df, date) in enumerate(zip(algo.history, source.trading_days)):
            self.assertEqual(df.index[-1], date, "Newest event doesn't \
                             match.")

            for sid in self.sids[:i]:
                self.assertIn(sid, df.columns)

            self.assertEqual(df.iloc[-1].iloc[-1], i)


class TestBatchTransformMinutely(TestCase):

    @classmethod
    def setUpClass(cls):
        cls.env = TradingEnvironment()
        cls.env.write_data(equities_identifiers=[0])

    @classmethod
    def tearDownClass(cls):
        del cls.env

    def setUp(self):
        setup_logger(self)
        start = pd.datetime(1990, 1, 3, 0, 0, 0, 0, pytz.utc)
        end = pd.datetime(1990, 1, 8, 0, 0, 0, 0, pytz.utc)
        self.sim_params = factory.create_simulation_parameters(
            start=start, end=end, env=self.env,
        )
        self.sim_params.emission_rate = 'daily'
        self.sim_params.data_frequency = 'minute'
        self.source, self.df = \
            factory.create_test_df_source(sim_params=self.sim_params,
                                          env=self.env,
                                          bars='minute')

    def tearDown(self):
        teardown_logger(self)

    def test_core(self):
        algo = BatchTransformAlgorithmMinute(sim_params=self.sim_params,
                                             env=self.env)
        algo.run(self.source)
        wl = int(algo.window_length * 6.5 * 60)
        for bt in algo.history[wl:]:
            self.assertEqual(len(bt), wl)

    def test_window_length(self):
        algo = BatchTransformAlgorithmMinute(sim_params=self.sim_params,
                                             env=self.env,
                                             window_length=1,
                                             refresh_period=0)
        algo.run(self.source)
        wl = int(algo.window_length * 6.5 * 60)
        np.testing.assert_array_equal(algo.history[:(wl - 1)],
                                      [None] * (wl - 1))
        for bt in algo.history[wl:]:
            self.assertEqual(len(bt), wl)


class TestBatchTransform(TestCase):

    @classmethod
    def setUpClass(cls):
        cls.env = TradingEnvironment()
        cls.env.write_data(equities_identifiers=[0])

    @classmethod
    def tearDownClass(cls):
        del cls.env

    def setUp(self):
        setup_logger(self)
        self.sim_params = factory.create_simulation_parameters(
            start=datetime(1990, 1, 1, tzinfo=pytz.utc),
            end=datetime(1990, 1, 8, tzinfo=pytz.utc),
            env=self.env
        )
        self.source, self.df = \
            factory.create_test_df_source(self.sim_params, self.env)

    def tearDown(self):
        teardown_logger(self)

    def test_core_functionality(self):
        algo = BatchTransformAlgorithm(sim_params=self.sim_params,
                                       env=self.env)
        algo.run(self.source)
        wl = algo.window_length
        # The following assertion depend on window length of 3
        self.assertEqual(wl, 3)
        # If window_length is 3, there should be 2 None events, as the
        # window fills up on the 3rd day.
        n_none_events = 2
        self.assertEqual(algo.history_return_price_class[:n_none_events],
                         [None] * n_none_events,
                         "First two iterations should return None." + "\n" +
                         "i.e. no returned values until window is full'" +
                         "%s" % (algo.history_return_price_class,))
        self.assertEqual(algo.history_return_price_decorator[:n_none_events],
                         [None] * n_none_events,
                         "First two iterations should return None." + "\n" +
                         "i.e. no returned values until window is full'" +
                         "%s" % (algo.history_return_price_decorator,))

        # After three Nones, the next value should be a data frame
        self.assertTrue(isinstance(
            algo.history_return_price_class[wl],
            pd.DataFrame)
        )

        # Test whether arbitrary fields can be added to datapanel
        field = algo.history_return_arbitrary_fields[-1]
        self.assertTrue(
            'arbitrary' in field.items,
            'datapanel should contain column arbitrary'
        )

        self.assertTrue(all(
            field['arbitrary'].values.flatten() ==
            [123] * algo.window_length),
            'arbitrary dataframe should contain only "test"'
        )

        for data in algo.history_return_sid_filter[wl:]:
            self.assertIn(0, data.columns)
            self.assertNotIn(1, data.columns)

        for data in algo.history_return_field_filter[wl:]:
            self.assertIn('price', data.items)
            self.assertNotIn('ignore', data.items)

        for data in algo.history_return_field_no_filter[wl:]:
            self.assertIn('price', data.items)
            self.assertIn('ignore', data.items)

        for data in algo.history_return_ticks[wl:]:
            self.assertTrue(isinstance(data, deque))

        for data in algo.history_return_not_full:
            self.assertIsNot(data, None)

        # test overloaded class
        for test_history in [algo.history_return_price_class,
                             algo.history_return_price_decorator]:
            # starting at window length, the window should contain
            # consecutive (of window length) numbers up till the end.
            for i in range(algo.window_length, len(test_history)):
                np.testing.assert_array_equal(
                    range(i - algo.window_length + 2, i + 2),
                    test_history[i].values.flatten()
                )

    def test_passing_of_args(self):
        algo = BatchTransformAlgorithm(1, kwarg='str',
                                       sim_params=self.sim_params,
                                       env=self.env)
        algo.run(self.source)
        self.assertEqual(algo.args, (1,))
        self.assertEqual(algo.kwargs, {'kwarg': 'str'})

        expected_item = ((1, ), {'kwarg': 'str'})
        self.assertEqual(
            algo.history_return_args,
            [
                # 1990-01-01 - market holiday, no event
                # 1990-01-02 - window not full
                None,
                # 1990-01-03 - window not full
                None,
                # 1990-01-04 - window now full, 3rd event
                expected_item,
                # 1990-01-05 - window now full
                expected_item,
                # 1990-01-08 - window now full
                expected_item
            ])
