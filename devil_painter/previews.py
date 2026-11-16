import gpu
from gpu_extras.batch import batch_for_shader

VERTEX_SOURCE = '''
void main()
{
    uvInterp = uv;
    gl_Position = ModelViewProjectionMatrix * vec4(pos, 0.0, 1.0);
}
'''
FRAGMENT_SOURCE = '''
vec3 to_display(vec3 linear)
{
    vec3 clamped = clamp(linear, 0.0, 1.0);
    return mix(clamped * 12.92, 1.055 * pow(clamped, vec3(1.0 / 2.4)) - 0.055, step(vec3(0.0031308), clamped));
}

void main()
{
    vec4 color = texture(image, uvInterp);
    if (mode == 1) {
        fragColor = vec4(vec3(color.a), 1.0);
    }
    else {
        fragColor = vec4(to_display(color.rgb), color.a);
    }
}
'''
_shader = []


def preview_shader():
    if not _shader:
        interface = gpu.types.GPUStageInterfaceInfo('devil_painter_preview')
        interface.smooth('VEC2', 'uvInterp')
        info = gpu.types.GPUShaderCreateInfo()
        info.push_constant('MAT4', 'ModelViewProjectionMatrix')
        info.push_constant('INT', 'mode')
        info.sampler(0, 'FLOAT_2D', 'image')
        info.vertex_in(0, 'VEC2', 'pos')
        info.vertex_in(1, 'VEC2', 'uv')
        info.vertex_out(interface)
        info.fragment_out(0, 'VEC4', 'fragColor')
        info.vertex_source(VERTEX_SOURCE)
        info.fragment_source(FRAGMENT_SOURCE)
        _shader.append(gpu.shader.create_from_info(info))
    return _shader[0]


def draw_image(image, rect, mask):
    shader = preview_shader()
    x, y, w, h = round(rect.x), round(rect.y), round(rect.w), round(rect.h)
    batch = batch_for_shader(shader, 'TRI_FAN', {'pos': ((x, y), (x + w, y), (x + w, y + h), (x, y + h)),
                                                 'uv': ((0, 0), (1, 0), (1, 1), (0, 1))})
    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_int('mode', 1 if mask else 0)
    shader.uniform_sampler('image', gpu.texture.from_image(image))
    batch.draw(shader)
