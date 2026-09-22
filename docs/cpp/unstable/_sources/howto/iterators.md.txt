# How to avoid materializing an input sequence

When an algorithm only reads its input once, you do not need to allocate and
fill a buffer first. Pass an iterator that produces the values on demand.

::::{tab-set}

:::{tab-item} C++

```cpp
#include <thrust/iterator/counting_iterator.h>
#include <thrust/reduce.h>

thrust::counting_iterator<int> first(0);
int total = thrust::reduce(first, first + 1000);
```

:::

:::{tab-item} Python

```python
from cuda.compute import CountingIterator

first = CountingIterator(0)
```

:::

::::

No device allocation happens, and nothing is written to memory before the
reduction runs.
