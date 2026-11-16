#pragma once
#include <stddef.h>
#define MALLOC_CAP_INTERNAL 0
#define MALLOC_CAP_8BIT 0
size_t heap_caps_get_largest_free_block(unsigned caps);
size_t heap_caps_get_free_size(unsigned caps);
#include <stdlib.h>
#define heap_caps_malloc(size, caps) malloc(size)
