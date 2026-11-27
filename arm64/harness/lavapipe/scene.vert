#version 450
// SPDX-License-Identifier: 0BSD
// Vertices with their own w, so the rasterizer interpolates with perspective.
layout(location = 0) in vec4 pos;
layout(location = 1) in vec2 uv;
layout(location = 2) in vec4 col;
layout(push_constant) uniform P { mat4 m; vec4 k; } p;
layout(location = 0) out vec2 o_uv;
layout(location = 1) out vec4 o_col;
layout(location = 2) out float o_s;
void main() {
  gl_Position = p.m * pos;
  o_uv = uv * p.k.x + p.k.y;
  o_col = col;
  o_s = sin(pos.x * p.k.z) * pos.y + pos.w;
}
