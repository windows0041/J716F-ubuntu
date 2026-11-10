#!/usr/bin/env python3
"""Report the EGL/GLES renderer through GBM on the J716F diagnostic system.

Creates a context but submits no draw commands and changes no display state.
--software explicitly selects Mesa's software GBM and Gallium paths.
"""
import argparse
import ctypes as C
import os
from pathlib import Path
import stat


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', default='/dev/dri/card1')
    parser.add_argument('--software', action='store_true')
    args = parser.parse_args()
    if b'lenovo,j716f' not in Path('/sys/firmware/devicetree/base/compatible').read_bytes().split(b'\0'):
        parser.error('J716F diagnostic system required')
    path = Path(args.device)
    info = path.stat()
    if path.parent != Path('/dev/dri') or not path.name.startswith('card') or not stat.S_ISCHR(info.st_mode) or os.major(info.st_rdev) != 226:
        parser.error('Use a DRM primary character device in /dev/dri')
    if args.software:
        for key, value in {'GBM_ALWAYS_SOFTWARE': 'true', 'LIBGL_ALWAYS_SOFTWARE': 'true', 'GALLIUM_DRIVER': 'llvmpipe'}.items():
            os.environ[key] = value
    egl = C.CDLL('libEGL.so.1')
    gbm = C.CDLL('libgbm.so.1')
    gles = C.CDLL('libGLESv2.so.2')
    P, I, U = C.c_void_p, C.c_int, C.c_uint
    def bind(lib, name, result, *params):
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = result, list(params)
        return fn
    create = bind(gbm, 'gbm_create_device', P, I)
    destroy = bind(gbm, 'gbm_device_destroy', None, P)
    display = bind(egl, 'eglGetPlatformDisplay', P, U, P, P)
    initialize = bind(egl, 'eglInitialize', U, P, C.POINTER(I), C.POINTER(I))
    choose = bind(egl, 'eglChooseConfig', U, P, C.POINTER(I), C.POINTER(P), I, C.POINTER(I))
    api = bind(egl, 'eglBindAPI', U, U)
    context = bind(egl, 'eglCreateContext', P, P, P, P, C.POINTER(I))
    current = bind(egl, 'eglMakeCurrent', U, P, P, P, P)
    delete = bind(egl, 'eglDestroyContext', U, P, P)
    terminate = bind(egl, 'eglTerminate', U, P)
    query = bind(egl, 'eglQueryString', C.c_char_p, P, I)
    string = bind(gles, 'glGetString', C.c_char_p, U)
    error = bind(egl, 'eglGetError', U)
    fd, device, dpy, ctx = None, None, None, None
    def require(value, step):
        if not value:
            raise RuntimeError(f'{step} failed; EGL error {error():#x}')
        return value
    try:
        fd = os.open(path, os.O_RDWR | os.O_CLOEXEC)
        device = require(create(fd), 'gbm_create_device')
        dpy = require(display(0x31D7, device, None), 'eglGetPlatformDisplay')
        major, minor = I(), I()
        require(initialize(dpy, C.byref(major), C.byref(minor)), 'eglInitialize')
        print(f'EGL {major.value}.{minor.value}: {query(dpy, 0x3053).decode()}', flush=True)
        require(api(0x30A0), 'eglBindAPI')
        config, count = P(), I()
        require(choose(dpy, (I * 3)(0x3040, 4, 0x3038), C.byref(config), 1, C.byref(count)), 'eglChooseConfig')
        require(count.value, 'GLES2 config selection')
        ctx = require(context(dpy, config, None, (I * 3)(0x3098, 2, 0x3038)), 'eglCreateContext')
        require(current(dpy, None, None, ctx), 'surfaceless eglMakeCurrent')
        for label, enum in [('GL_VENDOR', 0x1F00), ('GL_RENDERER', 0x1F01), ('GL_VERSION', 0x1F02)]:
            value = string(enum)
            print(label + ': ' + (value.decode() if value else '<missing>'), flush=True)
    finally:
        if dpy:
            current(dpy, None, None, None)
            if ctx:
                delete(dpy, ctx)
            terminate(dpy)
        if device:
            destroy(device)
        if fd is not None:
            os.close(fd)


if __name__ == '__main__':
    main()
