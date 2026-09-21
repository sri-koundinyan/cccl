# How to update a value from many threads safely

When several threads update the same location, use an atomic operation so the
read-modify-write cannot be interleaved.

::::{tab-set}

:::{tab-item} C++

```cpp
#include <cuda/atomic>

cuda::atomic<int, cuda::thread_scope_device> counter{0};
counter.fetch_add(1, cuda::memory_order_relaxed);
```

:::

:::{tab-item} Python

```python
from cuda.coop import atomic_add

atomic_add(counter, 1)
```

:::

::::

Prefer a scoped atomic over a raw intrinsic. The scope states how far the
guarantee has to reach, which is both safer and faster than assuming the
widest one.
