#!/usr/bin/env python3
"""Bounded J716F EGL/GLES offscreen shader/readback and GPU idle/resume check."""
import argparse
import ctypes as C
import json
import os
from pathlib import Path
import re
import stat
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['hardware', 'software'], required=True)
    parser.add_argument('--device', default='/dev/dri/renderD128')
    parser.add_argument('--cycles', type=int, default=3)
    parser.add_argument('--frames', type=int, default=2)
    parser.add_argument('--idle-seconds', type=float, default=1.5)
    parser.add_argument('--size', type=int, choices=[128, 512, 1024], default=128)
    args = parser.parse_args()
    if not (1 <= args.cycles <= 60 and 1 <= args.frames <= 64 and 0 <= args.idle_seconds <= 5):
        parser.error('Require bounded cycle/frame/idle values')
    if os.getuid() < 1000 or b'lenovo,j716f' not in Path('/proc/device-tree/compatible').read_bytes().split(b'\0'):
        parser.error('Run as a J716F desktop user')
    node = Path(args.device)
    info = node.stat()
    if node.parent != Path('/dev/dri') or not stat.S_ISCHR(info.st_mode) or os.major(info.st_rdev) != 226:
        parser.error('Expected DRM character device')
    for key in ['LIBGL_ALWAYS_SOFTWARE', 'GALLIUM_DRIVER', 'GBM_ALWAYS_SOFTWARE']:
        os.environ.pop(key, None)
    if args.mode == 'software':
        os.environ.update(LIBGL_ALWAYS_SOFTWARE='true', GALLIUM_DRIVER='llvmpipe', GBM_ALWAYS_SOFTWARE='true')
    egl, gbm, gl = (C.CDLL(name) for name in ['libEGL.so.1', 'libgbm.so.1', 'libGLESv2.so.2'])
    P, I, U, F = C.c_void_p, C.c_int, C.c_uint, C.c_float
    def bind(lib, name, result, *params):
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = result, list(params)
        return fn
    create_gbm = bind(gbm, 'gbm_create_device', P, I)
    destroy_gbm = bind(gbm, 'gbm_device_destroy', None, P)
    get_display = bind(egl, 'eglGetPlatformDisplay', P, U, P, P)
    initialize = bind(egl, 'eglInitialize', U, P, C.POINTER(I), C.POINTER(I))
    choose = bind(egl, 'eglChooseConfig', U, P, C.POINTER(I), C.POINTER(P), I, C.POINTER(I))
    api = bind(egl, 'eglBindAPI', U, U)
    create_context = bind(egl, 'eglCreateContext', P, P, P, P, C.POINTER(I))
    current = bind(egl, 'eglMakeCurrent', U, P, P, P, P)
    destroy_context = bind(egl, 'eglDestroyContext', U, P, P)
    terminate = bind(egl, 'eglTerminate', U, P)
    egl_error = bind(egl, 'eglGetError', U)
    get_string = bind(gl, 'glGetString', C.c_char_p, U)
    gl_error = bind(gl, 'glGetError', U)
    create_shader = bind(gl, 'glCreateShader', U, U)
    shader_source = bind(gl, 'glShaderSource', None, U, I, C.POINTER(C.c_char_p), C.POINTER(I))
    compile_shader = bind(gl, 'glCompileShader', None, U)
    shader_info = bind(gl, 'glGetShaderiv', None, U, U, C.POINTER(I))
    shader_log = bind(gl, 'glGetShaderInfoLog', None, U, I, C.POINTER(I), P)
    delete_shader = bind(gl, 'glDeleteShader', None, U)
    create_program = bind(gl, 'glCreateProgram', U)
    attach_shader = bind(gl, 'glAttachShader', None, U, U)
    attribute = bind(gl, 'glBindAttribLocation', None, U, U, C.c_char_p)
    link_program = bind(gl, 'glLinkProgram', None, U)
    program_info = bind(gl, 'glGetProgramiv', None, U, U, C.POINTER(I))
    use_program = bind(gl, 'glUseProgram', None, U)
    delete_program = bind(gl, 'glDeleteProgram', None, U)
    uniform_location = bind(gl, 'glGetUniformLocation', I, U, C.c_char_p)
    uniform = bind(gl, 'glUniform1f', None, I, F)
    gen_texture = bind(gl, 'glGenTextures', None, I, C.POINTER(U))
    bind_texture = bind(gl, 'glBindTexture', None, U, U)
    texture_parameter = bind(gl, 'glTexParameteri', None, U, U, I)
    texture_image = bind(gl, 'glTexImage2D', None, U, I, I, I, I, I, U, U, P)
    delete_texture = bind(gl, 'glDeleteTextures', None, I, C.POINTER(U))
    gen_framebuffer = bind(gl, 'glGenFramebuffers', None, I, C.POINTER(U))
    bind_framebuffer = bind(gl, 'glBindFramebuffer', None, U, U)
    framebuffer_texture = bind(gl, 'glFramebufferTexture2D', None, U, U, U, U, I)
    framebuffer_status = bind(gl, 'glCheckFramebufferStatus', U, U)
    delete_framebuffer = bind(gl, 'glDeleteFramebuffers', None, I, C.POINTER(U))
    gen_buffer = bind(gl, 'glGenBuffers', None, I, C.POINTER(U))
    bind_buffer = bind(gl, 'glBindBuffer', None, U, U)
    buffer_data = bind(gl, 'glBufferData', None, U, C.c_ssize_t, P, U)
    delete_buffer = bind(gl, 'glDeleteBuffers', None, I, C.POINTER(U))
    pointer = bind(gl, 'glVertexAttribPointer', None, U, I, U, C.c_ubyte, I, P)
    enable_attribute = bind(gl, 'glEnableVertexAttribArray', None, U)
    viewport = bind(gl, 'glViewport', None, I, I, I, I)
    draw = bind(gl, 'glDrawArrays', None, U, I, I)
    read_pixels = bind(gl, 'glReadPixels', None, I, I, I, I, U, U, P)
    finish = bind(gl, 'glFinish', None)
    def require(ok, message):
        if not ok:
            raise RuntimeError(message)
    def gpu_state():
        return Path('/sys/bus/platform/devices/3d00000.gpu/power/runtime_status').read_text().strip()
    def thermal():
        values = []
        for folder in Path('/sys/class/thermal').glob('thermal_zone*'):
            try:
                kind = (folder/'type').read_text().lower()
                if 'gpu' in kind or 'cpu' in kind:
                    value = int((folder/'temp').read_text())
                    if 0 < value < 130000:
                        values.append(value)
            except OSError:
                pass
        require(len(values) >= 4, 'Thermal telemetry unavailable')
        hottest = max(values)
        require(hottest < 80000, 'Temperature guard reached')
        return hottest
    fd = device = display = context = None
    shaders, program = [], 0
    tex, fbo, vbo = U(), U(), U()
    started = time.monotonic()
    peak = thermal()
    frames = 0
    try:
        fd = os.open(node, os.O_RDWR | os.O_CLOEXEC)
        device = create_gbm(fd)
        require(device, 'gbm_create_device failed')
        display = get_display(0x31D7, device, None)
        require(display, 'eglGetPlatformDisplay failed')
        major, minor = I(), I()
        require(initialize(display, C.byref(major), C.byref(minor)), f'eglInitialize failed {egl_error():#x}')
        require(api(0x30A0), 'eglBindAPI failed')
        config, count = P(), I()
        require(choose(display, (I*3)(0x3040, 4, 0x3038), C.byref(config), 1, C.byref(count)) and count.value, 'GLES config unavailable')
        context = create_context(display, config, None, (I*3)(0x3098, 2, 0x3038))
        require(context and current(display, None, None, context), f'EGL context failed {egl_error():#x}')
        strings = {label: get_string(enum).decode() for label, enum in [('vendor',0x1F00),('renderer',0x1F01),('version',0x1F02)]}
        print(json.dumps({'phase':'context', 'mode':args.mode, **strings}), flush=True)
        if args.mode == 'hardware':
            require(re.search(r'FD650|Adreno.*650', strings['renderer'], re.I), 'Expected Adreno 650 hardware renderer')
            require(not re.search(r'llvmpipe|softpipe|swrast', strings['renderer'], re.I), 'Software fallback detected')
        else:
            require('llvmpipe' in strings['renderer'].lower(), 'Expected software baseline')
        sources = [(0x8B31, b'attribute vec2 position; varying vec2 uv; void main(){uv=(position+1.0)*0.5;gl_Position=vec4(position,0.0,1.0);}'),
                   (0x8B30, b'precision mediump float; varying vec2 uv; uniform float blue; void main(){gl_FragColor=vec4(uv,blue,1.0);}')]
        for kind, source in sources:
            shader = create_shader(kind)
            shaders.append(shader)
            shader_source(shader, 1, (C.c_char_p*1)(source), None)
            compile_shader(shader)
            ok = I()
            shader_info(shader, 0x8B81, C.byref(ok))
            if not ok.value:
                log = C.create_string_buffer(2048)
                shader_log(shader, len(log), None, log)
                raise RuntimeError('Shader compile: '+log.value.decode(errors='replace'))
        program = create_program()
        for shader in shaders:
            attach_shader(program, shader)
        attribute(program, 0, b'position')
        link_program(program)
        ok = I()
        program_info(program, 0x8B82, C.byref(ok))
        require(ok.value, 'Shader link failed')
        use_program(program)
        blue = uniform_location(program, b'blue')
        require(blue >= 0, 'Uniform missing')
        gen_texture(1, C.byref(tex));bind_texture(0x0DE1, tex)
        for field in [0x2801, 0x2800]:
            texture_parameter(0x0DE1, field, 0x2600)
        texture_image(0x0DE1, 0, 0x1908, args.size, args.size, 0, 0x1908, 0x1401, None)
        gen_framebuffer(1, C.byref(fbo));bind_framebuffer(0x8D40, fbo)
        framebuffer_texture(0x8D40, 0x8CE0, 0x0DE1, tex, 0)
        require(framebuffer_status(0x8D40) == 0x8CD5, 'Framebuffer incomplete')
        vertices = (F*6)(-1,-1,3,-1,-1,3)
        gen_buffer(1, C.byref(vbo));bind_buffer(0x8892, vbo)
        buffer_data(0x8892, C.sizeof(vertices), vertices, 0x88E4)
        pointer(0, 2, 0x1406, 0, 0, None);enable_attribute(0)
        viewport(0, 0, args.size, args.size)
        pixels = (C.c_ubyte*(args.size*args.size*4))()
        points = [(0,0),(args.size//3,args.size//3),(args.size//2,args.size//2),(args.size-1,args.size-1)]
        for cycle in range(args.cycles):
            peak = max(peak, thermal())
            for frame in range(args.frames):
                value = .25 if frames % 2 == 0 else .75
                uniform(blue, value);draw(0x0004, 0, 3);finish()
                read_pixels(0,0,args.size,args.size,0x1908,0x1401,pixels)
                require(gl_error() == 0, 'GLES error during render/readback')
                for x,y in points:
                    offset=(y*args.size+x)*4
                    actual=list(pixels[offset:offset+4])
                    expected=[round((x+.5)/args.size*255),round((y+.5)/args.size*255),round(value*255),255]
                    require(all(abs(a-b)<=3 for a,b in zip(actual,expected)), f'Pixel mismatch cycle {cycle}: {actual} != {expected}')
                frames += 1
            active = gpu_state()
            peak = max(peak, thermal())
            time.sleep(args.idle_seconds)
            temperature = thermal()
            peak = max(peak, temperature)
            print(json.dumps({'phase':'cycle','cycle':cycle+1,'frames':frames,'gpu_after_render':active,'gpu_after_idle':gpu_state(),'temperature_mC':temperature}),flush=True)
        print(json.dumps({'completed':True,'mode':args.mode,'frames_checked':frames,'size':args.size,'cycles':args.cycles,'peak_temperature_mC':peak,'elapsed':round(time.monotonic()-started,3),**strings}),flush=True)
    finally:
        if display and context:
            if vbo.value:delete_buffer(1,C.byref(vbo))
            if fbo.value:delete_framebuffer(1,C.byref(fbo))
            if tex.value:delete_texture(1,C.byref(tex))
            if program:delete_program(program)
            for shader in shaders:delete_shader(shader)
            current(display,None,None,None)
            destroy_context(display,context)
        if display:terminate(display)
        if device:destroy_gbm(device)
        if fd is not None:os.close(fd)


if __name__ == '__main__':
    main()
