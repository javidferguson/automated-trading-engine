"""Benign IB notification codes must not be logged as errors.

IB reports routine notifications on the same channel as real failures, and
ib_async logs them all at ERROR. Code 10091 ("Delayed market data is available")
is emitted once per contract -- 82 lines in a single GEX scan -- while the data
arrives perfectly well. Left at ERROR it buries the failures that matter.
"""

import logging

from trading_engine.logging_setup import BENIGN_IB_CODES, _BenignIBCodeFilter


def record(msg, level=logging.ERROR):
    return logging.LogRecord("ib_async.wrapper", level, __file__, 1, msg, None, None)


def test_10091_is_demoted_from_error():
    r = record("Error 10091, reqId 170: Part of requested market data requires "
               "additional subscription for API.Delayed market data is available.")
    _BenignIBCodeFilter().filter(r)
    assert r.levelno == logging.DEBUG
    assert r.levelname == "DEBUG"


def test_farm_connection_notices_are_demoted():
    r = record("Error 2104, reqId -1: Market data farm connection is OK:usfarm")
    _BenignIBCodeFilter().filter(r)
    assert r.levelno == logging.DEBUG


def test_real_errors_are_left_alone():
    """200 = no security definition. That is a genuine failure."""
    r = record("Error 200, reqId 7: No security definition has been found for the request")
    assert _BenignIBCodeFilter().filter(r) is True
    assert r.levelno == logging.ERROR


def test_authorization_failures_are_left_alone():
    r = record("Error 502, reqId -1: Couldn't connect to TWS")
    assert _BenignIBCodeFilter().filter(r) is True
    assert r.levelno == logging.ERROR


def test_non_error_records_pass_through():
    r = record("Some ordinary message", level=logging.INFO)
    assert _BenignIBCodeFilter().filter(r) is True
    assert r.levelno == logging.INFO


def test_a_code_that_merely_starts_with_a_benign_prefix_is_not_demoted():
    """'Error 21049' must not match the 2104 entry."""
    r = record("Error 21049, reqId 1: something genuinely wrong")
    assert _BenignIBCodeFilter().filter(r) is True
    assert r.levelno == logging.ERROR


def test_benign_set_contains_the_delayed_data_code():
    assert 10091 in BENIGN_IB_CODES
