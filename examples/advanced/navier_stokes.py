"""
GPU version of https://github.com/salt-die/navier-stokes
"""
import random
from pathlib import Path
import numpy as np
from pyrr import matrix44

import moderngl_window
from moderngl_window import geometry

external_flow = .4
viscosity = .018  # Is it odd that negative viscosity still works?


class NavierStokes2D(moderngl_window.WindowConfig):
    title = "Navier Stokes 2D"
    resource_dir = (Path(__file__) / '../../resources').absolute()
    # window_size = (3440, 1440)
    aspect_ratio = None  # 1280 / 720
    # window_size = 512, 512
    # aspect_ratio = 1.0
    resizable = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # various vars
        self.m_proj = matrix44.create_orthogonal_projection(
            0, self.wnd.buffer_width,
            0, self.wnd.buffer_height,
            -1, 1,
            dtype='f4',
        )
        size = self.wnd.buffer_size

        # Geometry
        self.quad_fs = geometry.quad_fs()
        sprite_size = 9 * 4
        self.drop_geometry = geometry.quad_2d(size=(sprite_size, sprite_size))
        self.wall_geometry = geometry.quad_2d(size=(sprite_size, sprite_size))

        # Framebuffers
        self.momentum_texture_1 = self.ctx.texture(size, 1, dtype='f4')
        self.momentum_texture_1.repeat_x = True
        self.momentum_texture_1.repeat_y = True
        self.momentum_texture_2 = self.ctx.texture(size, 1, dtype='f4')
        self.momentum_texture_2.repeat_x = True
        self.momentum_texture_2.repeat_y = True
        self.pressure_texture_1 = self.ctx.texture(size, 1, dtype='f4')
        self.pressure_texture_2 = self.ctx.texture(size, 1, dtype='f4')
        self.walls_texture = self.ctx.texture(size, 1, dtype='f4')
        self.difference_texture = self.ctx.texture(size, 1, dtype='f4')

        self.momentum_fbo_1 = self.ctx.framebuffer(color_attachments=[self.momentum_texture_1])
        self.momentum_fbo_2 = self.ctx.framebuffer(color_attachments=[self.momentum_texture_2])
        self.pressure_fbo_1 = self.ctx.framebuffer(color_attachments=[self.pressure_texture_1])
        self.pressure_fbo_2 = self.ctx.framebuffer(color_attachments=[self.pressure_texture_2])
        self.walls_fbo = self.ctx.framebuffer(color_attachments=[self.walls_texture])
        self.difference_fbo = self.ctx.framebuffer(color_attachments=[self.difference_texture])

        # programs
        self.texture_prog = self.load_program('programs/navier-stokes/texture.glsl')
        self.drop_prog = self.load_program('programs/navier-stokes/drop.glsl')
        self.drop_prog['m_proj'].write(self.m_proj.tobytes())
        self.combine_prog = self.load_program('programs/navier-stokes/combine.glsl')
        self.combine_prog['pressure_texture'].value = 0
        self.combine_prog['wall_texture'].value = 1
        self.momentum_prog = self.load_program('programs/navier-stokes/momentum.glsl')
        self.momentum_prog['momentum_texture'].value = 0
        self.momentum_prog['pressure_texture'].value = 1
        self.flow_prog = self.load_program('programs/navier-stokes/flow.glsl')
        self.poisson_prog = self.load_program('programs/navier-stokes/poisson.glsl')
        self.pressure_prog = self.load_program('programs/navier-stokes/pressure.glsl')
        self.pressure_prog['pressure_texture'].value = 0
        self.pressure_prog['difference_texture'].value = 1

        self.reset()

    def reset(self):
        size = self.wnd.buffer_size
        momentum = np.zeros(size, dtype=np.float32).T
        # momentum[3 * size[0] // 8 : 5 * size[0] // 8,
        #          3 * size[1] // 8 : 5 * size[1] // 8] = .04
        self.momentum_texture_2.write(momentum.tobytes())

        pressure = np.zeros(size, dtype=np.float32).T
        # pressure[3 * size[0] // 8 : 5 * size[0] // 8,
        #          3 * size[1] // 8 : 5 * size[1] // 8] = 1
        self.pressure_texture_2.write(pressure.tobytes())

    def drop(self, x, y):
        rng = 40
        for i in range(10):
            pos = (
                x + int((random.random() - 0.5) * rng),
                self.wnd.buffer_size[1] - y + int((random.random() - 0.5) * rng)
            )
            # Render drop into pressure texture
            self.pressure_fbo_2.use()
            self.drop_prog['pos'].value = pos
            self.drop_prog['force'].value = random.random() * 2.0
            self.drop_prog['write_value'].value = 1.0
            # self.drop.use()
            self.drop_geometry.render(self.drop_prog)
            self.momentum_fbo_2.use()
            self.drop_prog['write_value'].value = 0.0
            self.drop_geometry.render(self.drop_prog)

    def wall(self, x, y):
        pos = x, self.wnd.buffer_height - y
        self.walls_fbo.use()
        self.drop_prog['pos'].value = pos
        self.drop_prog['force'].value = 1.0
        self.drop_prog['write_value'].value = 1.0
        self.drop_geometry.render(self.drop_prog)

    def render(self, time, frame_time):
        # calculate momentum
        self.momentum_fbo_1.use()
        self.momentum_texture_2.use(location=0)
        self.pressure_texture_2.use(location=1)
        self.quad_fs.render(self.momentum_prog)

        # External Flow
        self.momentum_swap()
        self.momentum_fbo_1.use()
        self.momentum_texture_2.use()
        self.quad_fs.render(self.flow_prog)

        # change in momentum
        # .. poisson momentum
        self.difference_fbo.use()
        self.momentum_texture_1.use()
        self.quad_fs.render(self.poisson_prog)
        # .. pressure
        self.pressure_fbo_1.use()
        self.pressure_texture_2.use(location=0)
        self.difference_texture.use(location=1)
        self.quad_fs.render(self.pressure_prog)

        # Wall boundary conditions
        # (for handling walls)

        # Render final result
        self.wnd.fbo.use()
        self.pressure_texture_1.use(location=0)
        self.walls_texture.use(location=1)
        self.quad_fs.render(self.combine_prog)

        self.momentum_swap()
        self.pressure_swap()

    def momentum_swap(self):
        self.momentum_texture_1, self.momentum_texture_2 = self.momentum_texture_2, self.momentum_texture_1
        self.momentum_fbo_1, self.momentum_fbo_2 = self.momentum_fbo_2, self.momentum_fbo_1

    def pressure_swap(self):
        self.pressure_texture_1, self.pressure_texture_2 = self.pressure_texture_2, self.pressure_texture_1
        self.pressure_fbo_1, self.pressure_fbo_2 = self.pressure_fbo_2, self.pressure_fbo_1

    def mouse_press_event(self, x, y, button):
        if button == self.wnd.mouse.left:
            self.drop(x, y)
        elif button == self.wnd.mouse.right:
            self.wall(x, y)

    def mouse_drag_event(self, x, y, dx, dy):
        if self.wnd.mouse_states.left:
            self.drop(x, y)
        elif self.wnd.mouse_states.right:
            self.wall(x, y)

    def key_event(self, key, action, modifiers):
        keys = self.wnd.keys

        if action == keys.ACTION_PRESS:
            if key == keys.R:
                self.reset()


if __name__ == '__main__':
    moderngl_window.run_window_config(NavierStokes2D)
