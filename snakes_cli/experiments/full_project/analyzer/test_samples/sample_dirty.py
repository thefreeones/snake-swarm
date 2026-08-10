"""
Dirty sample — should trigger all 5 rules at least once each.
"""
import os
import json


# Rule: mutable-default — 函数默认参数为可变对象
def add_item(item, target=[]):
    target.append(item)
    return target


def set_config(key, value, config={}):
    config[key] = value
    return config


# Rule: bare-except — 裸except
def risky_parse(data):
    try:
        return json.loads(data)
    except:
        return None


def process_file(path):
    try:
        with open(path) as f:
            return f.read()
    except Exception:
        return ""


# Rule: too-broad-try — try块超过20行
def long_try_block():
    try:
        a = 1
        b = 2
        c = 3
        d = 4
        e = 5
        f = 6
        g = 7
        h = 8
        i = 9
        j = 10
        k = 11
        l = 12
        m = 13
        n = 14
        o = 15
        p = 16
        q = 17
        r = 18
        s = 19
        t = 20
        u = 21
        v = 22
    except ValueError:
        return 0


# Rule: print-leftover — 调试残留print
def calculate(x):
    print("DEBUG: input is", x)
    result = x * 2
    print("result =", result)
    return result


# Rule: function-length — 函数超过50行
def very_long_function():
    a = 1
    b = 2
    c = 3
    d = 4
    e = 5
    f = 6
    g = 7
    h = 8
    i = 9
    j = 10
    k = 11
    l = 12
    m = 13
    n = 14
    o = 15
    p = 16
    q = 17
    r = 18
    s = 19
    t = 20
    u = 21
    v = 22
    w = 23
    x = 24
    y = 25
    z = 26
    aa = 27
    bb = 28
    cc = 29
    dd = 30
    ee = 31
    ff = 32
    gg = 33
    hh = 34
    ii = 35
    jj = 36
    kk = 37
    ll = 38
    mm = 39
    nn = 40
    oo = 41
    pp = 42
    qq = 43
    rr = 44
    ss = 45
    tt = 46
    uu = 47
    vv = 48
    ww = 49
    xx = 50
    yy = 51
    zz = 52
    return zz


# A clean function for contrast
def normal_function(x):
    return x + 1
