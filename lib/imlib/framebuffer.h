/*
 * SPDX-License-Identifier: MIT
 *
 * Copyright (C) 2013-2024 OpenMV, LLC.
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 *
 * Framebuffer functions.
 */
#ifndef __FRAMEBUFFER_H__
#define __FRAMEBUFFER_H__
#include <stdint.h>
#include "imlib.h"
#include "mutex.h"
#include "omv_common.h"

// DMA Buffers need to be aligned by cache lines or 16 bytes.
#ifndef __DCACHE_PRESENT
#define FRAMEBUFFER_ALIGNMENT    16
#else
#define FRAMEBUFFER_ALIGNMENT    __SCB_DCACHE_LINE_SIZE
#endif

typedef struct framebuffer {
    int32_t x, y;
    int32_t w, h;
    int32_t u, v;
    PIXFORMAT_STRUCT;
    uint32_t raw_size;
    uint32_t buff_size;
    uint32_t n_buffers;
    uint32_t frame_size;
    int32_t head;
    volatile int32_t tail;
    bool check_head;
    int32_t sampled_head;
    bool dynamic;
    OMV_ATTR_ALIGNED(uint8_t data[], FRAMEBUFFER_ALIGNMENT);
} framebuffer_t;

typedef enum {
    FB_NO_FLAGS   = (0 << 0),
    FB_PEEK       = (1 << 0),   // If set, will not move the head/tail.
    FB_INVALIDATE = (1 << 1),   // If set, invalidate the buffer on return.
} framebuffer_flags_t;

typedef struct vbuffer {
    // Used by snapshot code to figure out the jpeg size (bpp).
    int32_t offset;
    bool jpeg_buffer_overflow;
    // Used internally by frame buffer code.
    volatile bool waiting_for_data;
    bool reset_state;
    // Image data array.
    OMV_ATTR_ALIGNED(uint8_t data[], FRAMEBUFFER_ALIGNMENT);
} vbuffer_t;

typedef struct jpegbuffer {
    int32_t w, h;
    int32_t size;
    int32_t enabled;
    int32_t quality;
    omv_mutex_t lock;
    OMV_ATTR_ALIGNED(uint8_t pixels[], FRAMEBUFFER_ALIGNMENT);
} jpegbuffer_t;

extern jpegbuffer_t *jpegbuffer;

void framebuffer_init0();

framebuffer_t *framebuffer_get(size_t id);

int32_t framebuffer_get_x(framebuffer_t *fb);
int32_t framebuffer_get_y(framebuffer_t *fb);
int32_t framebuffer_get_u(framebuffer_t *fb);
int32_t framebuffer_get_v(framebuffer_t *fb);

int32_t framebuffer_get_width(framebuffer_t *fb);
int32_t framebuffer_get_height(framebuffer_t *fb);
int32_t framebuffer_get_depth(framebuffer_t *fb);

// Return the number of bytes in the current buffer.
uint32_t framebuffer_get_buffer_size(framebuffer_t *fb);

// Return the state of a buffer.
vbuffer_t *framebuffer_get_buffer(framebuffer_t *fb, int32_t index);

// Initializes a frame buffer instance.
void framebuffer_init_fb(framebuffer_t *fb, size_t size, bool dynamic);

// Initializes an image from the frame buffer.
void framebuffer_init_image(framebuffer_t *fb, image_t *img);

// Sets the frame buffer from an image.
void framebuffer_init_from_image(framebuffer_t *fb, image_t *img);

// Compress src image to the JPEG buffer if src is mutable, otherwise copy src to the JPEG buffer
// if the src is JPEG and fits in the JPEG buffer, or encode and stream src image to the IDE if not.
void framebuffer_update_jpeg_buffer(image_t *src);

// Clear the framebuffer FIFO. If fifo_flush is true, reset and discard all framebuffers,
// otherwise, retain the last frame in the fifo.
void framebuffer_flush_buffers(framebuffer_t *fb, bool fifo_flush);

// Set the number of virtual buffers in the frame buffer.
// If n_buffers = -1 the number of virtual buffers will be set to 3 each  if possible.
// If n_buffers = 1 the whole framebuffer is used. In this case, `frame_size` is ignored.
int framebuffer_set_buffers(framebuffer_t *fb, int32_t n_buffers);

// Call when done with the current vbuffer to mark it as free.
void framebuffer_free_current_buffer(framebuffer_t *fb);

// Call to do any heavy setup before frame capture.
void framebuffer_setup_buffers(framebuffer_t *fb);

// Sets the current frame buffer to the latest virtual frame buffer.
// Returns the buffer if it is ready or NULL if not...
// Pass FB_PEEK to get the next buffer but not take it.
vbuffer_t *framebuffer_get_head(framebuffer_t *fb, framebuffer_flags_t flags);

// Return the next vbuffer to store image data to or NULL if none.
// Pass FB_PEEK to get the next buffer but not commit it.
vbuffer_t *framebuffer_get_tail(framebuffer_t *fb, framebuffer_flags_t flags);

// Returns a pointer to the end of the framebuffer(s).
char *framebuffer_get_buffers_end(framebuffer_t *fb);

// Use this macro to get a pointer to the JPEG buffer.
#define JPEG_FB()    (jpegbuffer)

#endif /* __FRAMEBUFFER_H__ */
