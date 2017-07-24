# encoding: utf-8

'''

@author: ZiqiLiu


@file: prediction.py

@time: 2017/6/14 下午4:30

@desc:
'''

import numpy as np


def ctc_decode(softmax, classnum, lockout=4, thres=0.5, loose_thres=0.2):
    np.set_printoptions(precision=4, threshold=np.inf,
                        suppress=True)
    softmax = softmax[:, 1:classnum - 1]
    i = 0

    result = []
    length = softmax.shape[0]
    loose = False

    while (i < length):
        if loose:
            if (softmax[i, :].max() < loose_thres):
                if result[-1][0] != 3:
                    i += lockout
                    loose = False
                    continue
            else:
                if softmax[i, 2] > loose_thres:
                    result.append((3, i))
                    i += lockout
                    loose = False
                    continue
                else:
                    pos = softmax[i, :].argmax() + 1
                    if softmax[i, pos - 1] > 0.6:
                        if result[-1][1] + lockout < i:
                            result.append((pos, i))

        else:
            if (softmax[i, :].max() > thres):
                result.append((softmax[i, :].argmax() + 1, i))
                i += lockout
                if len(result) >= 3:
                    temp = [i[0] for i in result[-3:]]
                    if temp == [1, 2, 3]:
                        loose = True
                continue
        i += 1

    new_result = [0]
    for i in result:
        new_result.append(i[0])
        new_result.append(0)
    return np.asarray(new_result, dtype=np.int32)


def ctc_decode_strict(softmax, classnum, lockout=4, thres=0.5):
    np.set_printoptions(precision=4, threshold=np.inf,
                        suppress=True, )
    softmax = softmax[:, 1:classnum - 1]
    i = 0
    result = []
    length = softmax.shape[0]

    while (i < length):

        if (softmax[i, :].max() > thres):
            result.append((softmax[i, :].argmax() + 1, i))
            i += lockout
            continue
        i += 1
    new_result = [0]
    for i in result:
        new_result.append(i[0])
        new_result.append(0)
    return np.asarray(new_result, dtype=np.int32)


def ctc_predict(seq, labels):
    text = ''
    for i in seq:
        if i < 0:
            break
        if i > 0:
            text += str(i)
    for l in labels:
        if l in text:
            return 1
    return 0
    # return 1 if '1233' in text else 0


def decode(prediction, word_interval, golden):
    raw = golden
    keyword = list(raw)
    # prediction based on moving_avg,shape(t,p),sth like one-hot, but can may overlapping
    # prediction = prediction[:, 1:]
    num_class = prediction.shape[1]
    len_frame = prediction.shape[0]
    pre = 0
    inter = 0

    target = keyword.pop()
    # try:
    for frame in prediction:
        if frame.sum() > 0:
            if pre == 0:
                assert frame.sum() == 1
                index = np.nonzero(frame)[0]
                pre = index[0]
                if index == target:
                    if inter < word_interval:
                        if len(keyword) == 0:
                            return 1
                        target = keyword.pop()
                        continue
                keyword = list(raw)
                target = keyword.pop()
                inter = 0
                if index == target:
                    target = keyword.pop()
                    continue
            else:
                if frame[pre] == 1:
                    continue
                else:
                    index = np.nonzero(frame)[0]
                    pre = index
                    if index == target:
                        if len(keyword) == 0:
                            return 1
                        target = keyword.pop()
                    else:
                        keyword = list(raw)
                        target = keyword.pop()
                        if index == target:
                            if len(keyword) == 0:
                                return 1
                            target = keyword.pop()
                            continue
        else:
            if pre == 0:
                if len(raw) - len(keyword) > 1:
                    inter += 1
            else:
                pre = 0

    return 0


def evaluate(result, target):
    assert len(result) == len(target)
    # print(target)
    # print(result)
    xor = [a ^ b for a, b in zip(target, result)]
    miss = sum([a & b for a, b in zip(xor, target)])
    false_accept = sum([a & b for a, b in zip(xor, result)])
    return miss, sum(target), false_accept


def moving_average(array, n=5, padding=True):
    # array is 2D array, logits for one record, shape (t,p)
    # return shape (t,p)
    if n % 2 == 0:
        raise Exception('n must be odd')
    if len(array.shape) != 2:
        raise Exception('must be 2-D array.')
    if n > array.shape[0]:
        raise Exception(
            'n larger than array length. the shape:' + str(array.shape))
    if padding:
        pad_num = n // 2
        array = np.pad(array=array, pad_width=((pad_num, pad_num), (0, 0)),
                       mode='constant', constant_values=0)
    array = np.asarray([np.sum(array[i:i + n, :], axis=0) for i in
                        range(len(array) - 2 * pad_num)]) / n
    return array
