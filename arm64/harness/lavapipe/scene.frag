#version 450
// SPDX-License-Identifier: 0BSD
// Interpolated varyings, derivatives, trilinear filtering of an 8-bit mipmapped texture,
// bilinear filtering of a float texture, blending into two targets, and min/max/clamp of
// runtime subnormals (p.z) written as bits to a third, unblended one.
layout(location = 0) in vec2 uv;
layout(location = 1) in vec4 col;
layout(location = 2) in float s;
layout(location = 3) flat in uint vmax;
layout(set = 0, binding = 0) uniform sampler2D t8;
layout(set = 0, binding = 1) uniform sampler2D t32;
layout(push_constant) uniform P { mat4 m; vec4 k; vec4 z; } p;
layout(location = 0) out vec4 f32;
layout(location = 1) out vec4 u8;
layout(location = 2) out uvec4 u32;
void main() {
  vec4 a = texture(t8, uv);
  vec4 b = texture(t32, uv * 0.37 + vec2(s * 0.01, 0.0));
  vec4 g = textureGrad(t8, uv.yx * 1.7, dFdx(uv) * 3.1, dFdy(uv) * 0.6);
  vec2 dd = fwidth(uv * 41.0);
  f32 = vec4(a.r * b.g + col.b, sin(uv.x * 23.0) * s + b.a, dd.x * p.k.w + g.b, col.a * 0.75);
  u32 = uvec4(floatBitsToUint(min(p.z.x, uv.x)), floatBitsToUint(max(p.z.y, -uv.y)), vmax,
               floatBitsToUint(clamp(p.z.x, -abs(uv.x), abs(uv.y) + 1.0)));
  u8 = vec4(mix(a.rgb, g.gbr, col.a) * col.rgb + b.rgb * 0.25, col.a);
}
