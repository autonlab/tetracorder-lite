# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/autonlab/tetracorder-lite/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                         |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|----------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| tetrapy/\_\_init\_\_.py      |       34 |        0 |        4 |        0 |    100% |           |
| tetrapy/\_\_main\_\_.py      |       96 |       16 |        2 |        0 |     84% |58-59, 67-68, 76-77, 85-86, 95-96, 104-105, 113-114, 122-123 |
| tetrapy/aggregate.py         |      180 |        6 |       62 |        6 |     94% |201-204, 260, 342-\>347, 433, 588-\>590, 590-\>593 |
| tetrapy/config.py            |      114 |        0 |       58 |        1 |     99% | 146-\>149 |
| tetrapy/conv/\_\_init\_\_.py |        4 |        0 |        0 |        0 |    100% |           |
| tetrapy/conv/convolve.py     |       79 |        3 |       22 |        3 |     94% |140-141, 191, 203-\>193 |
| tetrapy/conv/library.py      |      101 |        0 |       18 |        0 |    100% |           |
| tetrapy/conv/specpr.py       |      123 |        2 |       16 |        0 |     99% |   331-332 |
| tetrapy/per\_reference.py    |      335 |       19 |      154 |       20 |     92% |96, 117, 130, 142, 146, 164, 172-173, 196, 208, 213, 228, 235, 258, 269, 285, 292-\>301, 328, 363, 428-\>427, 502-\>504, 506 |
| tetrapy/pipeline.py          |       58 |        4 |        2 |        0 |     93% |99-100, 214-216 |
| tetrapy/postprocess.py       |      111 |        5 |       38 |        1 |     96% |143, 304-307 |
| tetrapy/sensor.py            |      127 |        3 |       56 |        3 |     97% |406, 524, 531 |
| tetrapy/tetra.py             |       85 |        1 |       28 |        4 |     96% |115-\>130, 130-\>139, 143-\>146, 226 |
| tetrapy/tetracorder.py       |      173 |        9 |       84 |        4 |     94% |114-\>122, 418, 501, 503-\>506, 570-582 |
| tetrapy/utils.py             |       30 |        0 |        4 |        1 |     97% |   44-\>47 |
| **TOTAL**                    | **1650** |   **68** |  **548** |   **43** | **95%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/autonlab/tetracorder-lite/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/autonlab/tetracorder-lite/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/autonlab/tetracorder-lite/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/autonlab/tetracorder-lite/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2Fautonlab%2Ftetracorder-lite%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/autonlab/tetracorder-lite/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.