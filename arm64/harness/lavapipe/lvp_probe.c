// SPDX-License-Identifier: 0BSD
// Runs math.comp and the scene (scene.vert, scene.frag) on the lavapipe library given on
// the command line, loaded directly as Firefox loads it (no loader), and writes the bytes
// they produce to <out dir>: compute.bin, scene-f32.bin (RGBA32F) and scene-u8.bin (RGBA8).
// Every input is made from integers here, so both architectures feed the same bits.
//   lvp_probe <libvulkan_lvp.so> <dir with the .spv files> <out dir>
#define VK_NO_PROTOTYPES
#include <vulkan/vulkan.h>
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static PFN_vkGetInstanceProcAddr gipa;
static PFN_vkGetDeviceProcAddr gdpa;
static VkInstance inst;
static VkDevice dev;
static VkPhysicalDevice pd;
static VkQueue q;
static uint32_t qf;
static const char *spv, *out;

#define I(n) PFN_vk##n n = (PFN_vk##n)gipa(inst, "vk" #n)
#define D(n) PFN_vk##n n = (PFN_vk##n)gdpa(dev, "vk" #n)
#define CK(x) do { VkResult r_ = (x); if (r_ != VK_SUCCESS) { printf("FAIL %s = %d (line %d)\n", #x, r_, __LINE__); exit(1); } } while (0)

enum { N = 4096, K = 64, W = 128, H = 96, T8 = 64, T32 = 16 };

static uint64_t hash(uint64_t x) {  // splitmix64
  x += 0x9e3779b97f4a7c15ull;
  x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ull;
  x = (x ^ (x >> 27)) * 0x94d049bb133111ebull;
  return x ^ (x >> 31);
}
// A finite float from integers: random sign and mantissa, exponent 2^-8..2^8, and every
// 37th a subnormal.
static float num(uint64_t i) {
  uint64_t h = hash(i);
  uint32_t bits = (uint32_t)(h & 0x807fffffu);
  if (i % 37) bits |= (uint32_t)(127 + (int)((h >> 32) % 17) - 8) << 23;
  float f; memcpy(&f, &bits, 4); return f;
}
// 0..1 from integers: k / 2^24.
static float unit(uint64_t i) { return (float)(hash(i) >> 40) / 16777216.0f; }

static void save(const char *name, const void *p, size_t n) {
  char path[4096]; snprintf(path, sizeof path, "%s/%s", out, name);
  FILE *f = fopen(path, "wb"); if (!f || fwrite(p, 1, n, f) != n) { printf("cannot write %s\n", path); exit(1); }
  fclose(f);
}
static VkShaderModule shader(const char *name) {
  D(CreateShaderModule);
  char path[4096]; snprintf(path, sizeof path, "%s/%s", spv, name);
  FILE *f = fopen(path, "rb"); if (!f) { printf("no %s\n", path); exit(1); }
  fseek(f, 0, SEEK_END); size_t n = ftell(f); fseek(f, 0, SEEK_SET);
  uint32_t *c = malloc(n); if (fread(c, 1, n, f) != n) { printf("short %s\n", path); exit(1); } fclose(f);
  VkShaderModuleCreateInfo ci = {VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, 0, 0, n, c};
  VkShaderModule m; CK(CreateShaderModule(dev, &ci, 0, &m)); return m;
}
static uint32_t memtype(uint32_t bits, VkMemoryPropertyFlags want) {
  I(GetPhysicalDeviceMemoryProperties); VkPhysicalDeviceMemoryProperties mp;
  GetPhysicalDeviceMemoryProperties(pd, &mp);
  for (uint32_t i = 0; i < mp.memoryTypeCount; i++)
    if ((bits & (1u << i)) && (mp.memoryTypes[i].propertyFlags & want) == want) return i;
  printf("no memory type\n"); exit(1);
}
static VkBuffer buffer(VkDeviceSize size, VkBufferUsageFlags usage, void **map) {
  D(CreateBuffer); D(GetBufferMemoryRequirements); D(AllocateMemory); D(BindBufferMemory); D(MapMemory);
  VkBufferCreateInfo ci = {VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, 0, 0, size, usage};
  VkBuffer b; CK(CreateBuffer(dev, &ci, 0, &b));
  VkMemoryRequirements r; GetBufferMemoryRequirements(dev, b, &r);
  VkMemoryAllocateInfo ai = {VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, 0, r.size,
    memtype(r.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)};
  VkDeviceMemory m; CK(AllocateMemory(dev, &ai, 0, &m)); CK(BindBufferMemory(dev, b, m, 0));
  CK(MapMemory(dev, m, 0, VK_WHOLE_SIZE, 0, map)); memset(*map, 0, size);
  return b;
}
static VkImage image(VkFormat fmt, uint32_t w, uint32_t h, uint32_t mips, VkImageUsageFlags usage, VkImageView *view) {
  D(CreateImage); D(GetImageMemoryRequirements); D(AllocateMemory); D(BindImageMemory); D(CreateImageView);
  VkImageCreateInfo ici = {VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, 0, 0, VK_IMAGE_TYPE_2D, fmt, {w, h, 1}, mips, 1,
    VK_SAMPLE_COUNT_1_BIT, VK_IMAGE_TILING_OPTIMAL, usage, VK_SHARING_MODE_EXCLUSIVE, 0, 0, VK_IMAGE_LAYOUT_UNDEFINED};
  VkImage img; CK(CreateImage(dev, &ici, 0, &img));
  VkMemoryRequirements r; GetImageMemoryRequirements(dev, img, &r);
  VkMemoryAllocateInfo ai = {VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, 0, r.size, memtype(r.memoryTypeBits, 0)};
  VkDeviceMemory m; CK(AllocateMemory(dev, &ai, 0, &m)); CK(BindImageMemory(dev, img, m, 0));
  VkImageViewCreateInfo vci = {VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, 0, 0, img, VK_IMAGE_VIEW_TYPE_2D, fmt,
    {0}, {VK_IMAGE_ASPECT_COLOR_BIT, 0, mips, 0, 1}};
  CK(CreateImageView(dev, &vci, 0, view));
  return img;
}
static void barrier(VkCommandBuffer cb, VkImage img, uint32_t mips, VkImageLayout from, VkImageLayout to) {
  D(CmdPipelineBarrier);
  VkImageMemoryBarrier b = {VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, 0, VK_ACCESS_MEMORY_WRITE_BIT,
    VK_ACCESS_MEMORY_READ_BIT | VK_ACCESS_MEMORY_WRITE_BIT, from, to, VK_QUEUE_FAMILY_IGNORED, VK_QUEUE_FAMILY_IGNORED,
    img, {VK_IMAGE_ASPECT_COLOR_BIT, 0, mips, 0, 1}};
  CmdPipelineBarrier(cb, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, 0, 0, 0, 0, 0, 1, &b);
}
static VkCommandBuffer begin(void) {
  D(CreateCommandPool); D(AllocateCommandBuffers); D(BeginCommandBuffer);
  VkCommandPoolCreateInfo pc = {VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, 0, 0, qf};
  VkCommandPool pool; CK(CreateCommandPool(dev, &pc, 0, &pool));
  VkCommandBufferAllocateInfo ai = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, 0, pool, VK_COMMAND_BUFFER_LEVEL_PRIMARY, 1};
  VkCommandBuffer cb; CK(AllocateCommandBuffers(dev, &ai, &cb));
  VkCommandBufferBeginInfo bi = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
  CK(BeginCommandBuffer(cb, &bi)); return cb;
}
static void submit(VkCommandBuffer cb) {
  D(EndCommandBuffer); D(QueueSubmit); D(QueueWaitIdle);
  CK(EndCommandBuffer(cb));
  VkSubmitInfo si = {VK_STRUCTURE_TYPE_SUBMIT_INFO, 0, 0, 0, 0, 1, &cb};
  CK(QueueSubmit(q, 1, &si, VK_NULL_HANDLE)); CK(QueueWaitIdle(q));
}

static void run_compute(void) {
  D(CreateDescriptorSetLayout); D(CreatePipelineLayout); D(CreateComputePipelines); D(CreateDescriptorPool);
  D(AllocateDescriptorSets); D(UpdateDescriptorSets); D(CmdBindPipeline); D(CmdBindDescriptorSets); D(CmdDispatch);
  void *in, *res;
  VkBuffer bi = buffer(N * 16, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, &in);
  VkBuffer bo = buffer(N * K * 4, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, &res);
  for (uint64_t i = 0; i < N * 4; i++) ((float *)in)[i] = num(i);
  VkDescriptorSetLayoutBinding lb[2] = {{0, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT},
                                        {1, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT}};
  VkDescriptorSetLayoutCreateInfo lci = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, 0, 0, 2, lb};
  VkDescriptorSetLayout sl; CK(CreateDescriptorSetLayout(dev, &lci, 0, &sl));
  VkPipelineLayoutCreateInfo pli = {VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, 0, 0, 1, &sl};
  VkPipelineLayout pl; CK(CreatePipelineLayout(dev, &pli, 0, &pl));
  VkComputePipelineCreateInfo cpi = {VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO, 0, 0,
    {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, 0, 0, VK_SHADER_STAGE_COMPUTE_BIT, shader("math.comp.spv"), "main"}, pl};
  VkPipeline p; CK(CreateComputePipelines(dev, VK_NULL_HANDLE, 1, &cpi, 0, &p));
  VkDescriptorPoolSize ps = {VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 2};
  VkDescriptorPoolCreateInfo dpi = {VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, 0, 0, 1, 1, &ps};
  VkDescriptorPool dp; CK(CreateDescriptorPool(dev, &dpi, 0, &dp));
  VkDescriptorSetAllocateInfo dai = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO, 0, dp, 1, &sl};
  VkDescriptorSet ds; CK(AllocateDescriptorSets(dev, &dai, &ds));
  VkDescriptorBufferInfo dbi[2] = {{bi, 0, VK_WHOLE_SIZE}, {bo, 0, VK_WHOLE_SIZE}};
  VkWriteDescriptorSet w = {VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, 0, ds, 0, 0, 2, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 0, dbi};
  UpdateDescriptorSets(dev, 1, &w, 0, 0);
  VkCommandBuffer cb = begin();
  CmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_COMPUTE, p);
  CmdBindDescriptorSets(cb, VK_PIPELINE_BIND_POINT_COMPUTE, pl, 0, 1, &ds, 0, 0);
  CmdDispatch(cb, N / 64, 1, 1);
  submit(cb);
  save("compute.bin", res, N * K * 4);
  printf("compute: %d rows of %d results\n", N, K);
}

static void run_scene(void) {
  D(CreateDescriptorSetLayout); D(CreatePipelineLayout); D(CreateGraphicsPipelines); D(CreateDescriptorPool);
  D(AllocateDescriptorSets); D(UpdateDescriptorSets); D(CmdBindPipeline); D(CmdBindDescriptorSets); D(CmdDraw);
  D(CmdCopyBufferToImage); D(CmdCopyImageToBuffer); D(CmdBeginRendering); D(CmdEndRendering);
  D(CreateSampler); D(CmdBindVertexBuffers); D(CmdPushConstants);
  I(GetPhysicalDeviceFormatProperties);
  VkFormatProperties fp;
  GetPhysicalDeviceFormatProperties(pd, VK_FORMAT_R32G32B32A32_SFLOAT, &fp);
  VkFormatFeatureFlags need = VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT | VK_FORMAT_FEATURE_COLOR_ATTACHMENT_BLEND_BIT;
  if ((fp.optimalTilingFeatures & need) != need) { printf("FAIL: RGBA32F cannot be filtered or blended here\n"); exit(1); }

  // Textures: an 8-bit one with every mip level its own noise, and a float one.
  const uint32_t mips = 7;
  size_t t8bytes = 0; for (uint32_t l = 0; l < mips; l++) t8bytes += (size_t)(T8 >> l) * (T8 >> l) * 4;
  void *stage;
  VkBuffer sb = buffer(t8bytes + T32 * T32 * 16, VK_BUFFER_USAGE_TRANSFER_SRC_BIT, &stage);
  for (size_t i = 0; i < t8bytes; i++) ((uint8_t *)stage)[i] = (uint8_t)(hash(1000000 + i) >> 56);
  float *t32 = (float *)((char *)stage + t8bytes);
  for (uint32_t i = 0; i < T32 * T32 * 4; i++) t32[i] = num(2000000 + i);
  VkImageView v8, v32, vf, vu;
  VkImage i8 = image(VK_FORMAT_R8G8B8A8_UNORM, T8, T8, mips, VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT, &v8);
  VkImage i32 = image(VK_FORMAT_R32G32B32A32_SFLOAT, T32, T32, 1, VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT, &v32);
  VkImage rf = image(VK_FORMAT_R32G32B32A32_SFLOAT, W, H, 1, VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT, &vf);
  VkImage ru = image(VK_FORMAT_R8G8B8A8_UNORM, W, H, 1, VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT, &vu);
  VkSamplerCreateInfo sci = {VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO, 0, 0, VK_FILTER_LINEAR, VK_FILTER_LINEAR,
    VK_SAMPLER_MIPMAP_MODE_LINEAR, VK_SAMPLER_ADDRESS_MODE_REPEAT, VK_SAMPLER_ADDRESS_MODE_MIRRORED_REPEAT,
    VK_SAMPLER_ADDRESS_MODE_REPEAT, 0.25f, VK_FALSE, 1.0f, VK_FALSE, VK_COMPARE_OP_NEVER, 0.0f, 16.0f};
  VkSampler smp; CK(CreateSampler(dev, &sci, 0, &smp));

  // Two overlapping quads, each vertex with its own w, colour and alpha.
  enum { NV = 12 };
  void *vmap; VkBuffer vb = buffer(NV * 40, VK_BUFFER_USAGE_VERTEX_BUFFER_BIT, &vmap);
  static const float corner[6][2] = {{0, 0}, {1, 0}, {0, 1}, {1, 0}, {1, 1}, {0, 1}};
  for (int i = 0; i < NV; i++) {
    float *o = (float *)vmap + i * 10, w = 0.6f + 1.4f * unit(3000 + i);
    float x = corner[i % 6][0], y = corner[i % 6][1], off = i < 6 ? -0.9f : -0.4f;
    o[0] = (off + 1.3f * x + 0.05f * unit(3100 + i)) * w; o[1] = (off + 1.25f * y) * w;
    o[2] = 0.5f * unit(3200 + i) * w; o[3] = w;
    o[4] = x * 2.7f - 0.3f; o[5] = y * 1.9f + 0.1f;
    for (int c = 0; c < 4; c++) o[6 + c] = unit(3300 + i * 4 + c);
  }
  struct { float m[16], k[4]; } pc = {
    {0.97f, 0.11f, 0, 0, -0.08f, 1.03f, 0, 0, 0, 0, 1, 0, 0.02f, -0.03f, 0, 1}, {1.13f, 0.07f, 3.7f, 0.31f}};

  VkDescriptorSetLayoutBinding lb[2] = {{0, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_FRAGMENT_BIT},
                                        {1, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_FRAGMENT_BIT}};
  VkDescriptorSetLayoutCreateInfo lci = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, 0, 0, 2, lb};
  VkDescriptorSetLayout sl; CK(CreateDescriptorSetLayout(dev, &lci, 0, &sl));
  VkPushConstantRange pcr = {VK_SHADER_STAGE_VERTEX_BIT | VK_SHADER_STAGE_FRAGMENT_BIT, 0, sizeof pc};
  VkPipelineLayoutCreateInfo pli = {VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, 0, 0, 1, &sl, 1, &pcr};
  VkPipelineLayout pl; CK(CreatePipelineLayout(dev, &pli, 0, &pl));
  VkPipelineShaderStageCreateInfo st[2] = {
    {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, 0, 0, VK_SHADER_STAGE_VERTEX_BIT, shader("scene.vert.spv"), "main"},
    {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, 0, 0, VK_SHADER_STAGE_FRAGMENT_BIT, shader("scene.frag.spv"), "main"}};
  VkVertexInputBindingDescription vbd = {0, 40, VK_VERTEX_INPUT_RATE_VERTEX};
  VkVertexInputAttributeDescription vad[3] = {{0, 0, VK_FORMAT_R32G32B32A32_SFLOAT, 0},
    {1, 0, VK_FORMAT_R32G32_SFLOAT, 16}, {2, 0, VK_FORMAT_R32G32B32A32_SFLOAT, 24}};
  VkPipelineVertexInputStateCreateInfo vi = {VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO, 0, 0, 1, &vbd, 3, vad};
  VkPipelineInputAssemblyStateCreateInfo ia = {VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO, 0, 0, VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST};
  VkViewport vp = {0, 0, W, H, 0, 1}; VkRect2D sc = {{0, 0}, {W, H}};
  VkPipelineViewportStateCreateInfo vs = {VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO, 0, 0, 1, &vp, 1, &sc};
  VkPipelineRasterizationStateCreateInfo rs = {VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO};
  rs.cullMode = VK_CULL_MODE_NONE; rs.lineWidth = 1.0f;
  VkPipelineMultisampleStateCreateInfo ms = {VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO, 0, 0, VK_SAMPLE_COUNT_1_BIT};
  VkPipelineColorBlendAttachmentState ba = {VK_TRUE, VK_BLEND_FACTOR_SRC_ALPHA, VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA, VK_BLEND_OP_ADD,
    VK_BLEND_FACTOR_ONE, VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA, VK_BLEND_OP_ADD, 0xf};
  VkPipelineColorBlendAttachmentState bas[2] = {ba, ba};
  VkPipelineColorBlendStateCreateInfo cbs = {VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO, 0, 0, VK_FALSE, 0, 2, bas};
  VkFormat fmts[2] = {VK_FORMAT_R32G32B32A32_SFLOAT, VK_FORMAT_R8G8B8A8_UNORM};
  VkPipelineRenderingCreateInfo rci = {VK_STRUCTURE_TYPE_PIPELINE_RENDERING_CREATE_INFO, 0, 0, 2, fmts};
  VkGraphicsPipelineCreateInfo gpi = {VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO, &rci, 0, 2, st, &vi, &ia, 0, &vs, &rs, &ms, 0, &cbs, 0, pl};
  VkPipeline p; CK(CreateGraphicsPipelines(dev, VK_NULL_HANDLE, 1, &gpi, 0, &p));
  VkDescriptorPoolSize ps = {VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 2};
  VkDescriptorPoolCreateInfo dpi = {VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, 0, 0, 1, 1, &ps};
  VkDescriptorPool dp; CK(CreateDescriptorPool(dev, &dpi, 0, &dp));
  VkDescriptorSetAllocateInfo dai = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO, 0, dp, 1, &sl};
  VkDescriptorSet ds; CK(AllocateDescriptorSets(dev, &dai, &ds));
  VkDescriptorImageInfo ii[2] = {{smp, v8, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL}, {smp, v32, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL}};
  VkWriteDescriptorSet w = {VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, 0, ds, 0, 0, 2, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, ii};
  UpdateDescriptorSets(dev, 1, &w, 0, 0);

  void *rmap;
  VkBuffer rb = buffer(W * H * 16 + W * H * 4, VK_BUFFER_USAGE_TRANSFER_DST_BIT, &rmap);
  VkCommandBuffer cb = begin();
  barrier(cb, i8, mips, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
  barrier(cb, i32, 1, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
  VkDeviceSize at = 0;
  for (uint32_t l = 0; l < mips; l++) {
    VkBufferImageCopy c = {at, 0, 0, {VK_IMAGE_ASPECT_COLOR_BIT, l, 0, 1}, {0, 0, 0}, {T8 >> l, T8 >> l, 1}};
    CmdCopyBufferToImage(cb, sb, i8, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &c);
    at += (VkDeviceSize)(T8 >> l) * (T8 >> l) * 4;
  }
  VkBufferImageCopy c32 = {t8bytes, 0, 0, {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, {0, 0, 0}, {T32, T32, 1}};
  CmdCopyBufferToImage(cb, sb, i32, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &c32);
  barrier(cb, i8, mips, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL);
  barrier(cb, i32, 1, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL);
  barrier(cb, rf, 1, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL);
  barrier(cb, ru, 1, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL);
  VkRenderingAttachmentInfo att[2] = {
    {VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO, 0, vf, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL, 0, 0, 0,
     VK_ATTACHMENT_LOAD_OP_CLEAR, VK_ATTACHMENT_STORE_OP_STORE, {.color.float32 = {0.1f, 0.2f, 0.3f, 0.4f}}},
    {VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO, 0, vu, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL, 0, 0, 0,
     VK_ATTACHMENT_LOAD_OP_CLEAR, VK_ATTACHMENT_STORE_OP_STORE, {.color.float32 = {0.6f, 0.3f, 0.1f, 0.9f}}}};
  VkRenderingInfo ri = {VK_STRUCTURE_TYPE_RENDERING_INFO, 0, 0, {{0, 0}, {W, H}}, 1, 0, 2, att};
  CmdBeginRendering(cb, &ri);
  CmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_GRAPHICS, p);
  CmdBindDescriptorSets(cb, VK_PIPELINE_BIND_POINT_GRAPHICS, pl, 0, 1, &ds, 0, 0);
  CmdPushConstants(cb, pl, VK_SHADER_STAGE_VERTEX_BIT | VK_SHADER_STAGE_FRAGMENT_BIT, 0, sizeof pc, &pc);
  VkDeviceSize zero = 0; CmdBindVertexBuffers(cb, 0, 1, &vb, &zero);
  CmdDraw(cb, NV, 1, 0, 0);
  CmdEndRendering(cb);
  barrier(cb, rf, 1, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
  barrier(cb, ru, 1, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
  VkBufferImageCopy cf = {0, 0, 0, {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, {0, 0, 0}, {W, H, 1}};
  VkBufferImageCopy cu = {W * H * 16, 0, 0, {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, {0, 0, 0}, {W, H, 1}};
  CmdCopyImageToBuffer(cb, rf, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, rb, 1, &cf);
  CmdCopyImageToBuffer(cb, ru, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, rb, 1, &cu);
  submit(cb);
  save("scene-f32.bin", rmap, W * H * 16);
  save("scene-u8.bin", (char *)rmap + W * H * 16, W * H * 4);
  // A scene that drew nothing would compare equal and prove nothing.
  uint32_t clear; float cv = 0.1f; memcpy(&clear, &cv, 4);
  int drawn = 0;
  for (int i = 0; i < W * H; i++) drawn += ((uint32_t *)rmap)[i * 4] != clear;
  printf("scene: %dx%d, %d of %d pixels drawn\n", W, H, drawn, W * H);
  if (drawn < W * H / 4) { printf("FAIL: the scene drew too little\n"); exit(1); }
}

int main(int argc, char **argv) {
  if (argc != 4) { printf("usage: lvp_probe <libvulkan_lvp.so> <spv dir> <out dir>\n"); return 2; }
  spv = argv[2]; out = argv[3];
  void *lib = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
  if (!lib) { printf("dlopen: %s\n", dlerror()); return 1; }
  gipa = (PFN_vkGetInstanceProcAddr)dlsym(lib, "vkGetInstanceProcAddr");
  PFN_vkCreateInstance CreateInstance = (PFN_vkCreateInstance)gipa(0, "vkCreateInstance");
  VkApplicationInfo app = {VK_STRUCTURE_TYPE_APPLICATION_INFO, 0, "lvp_probe", 1, 0, 0, VK_API_VERSION_1_3};
  VkInstanceCreateInfo ic = {VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, 0, 0, &app};
  CK(CreateInstance(&ic, 0, &inst));
  I(EnumeratePhysicalDevices); I(GetPhysicalDeviceProperties); I(CreateDevice); I(GetPhysicalDeviceQueueFamilyProperties);
  uint32_t n = 1; CK(EnumeratePhysicalDevices(inst, &n, &pd));
  VkPhysicalDeviceProperties pr; GetPhysicalDeviceProperties(pd, &pr);
  printf("device %s\n", pr.deviceName);
  uint32_t nq = 8; VkQueueFamilyProperties qp[8]; GetPhysicalDeviceQueueFamilyProperties(pd, &nq, qp);
  for (qf = 0; qf < nq && !(qp[qf].queueFlags & VK_QUEUE_GRAPHICS_BIT); qf++) {}
  float prio = 1.0f;
  VkDeviceQueueCreateInfo dq = {VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, 0, 0, qf, 1, &prio};
  VkPhysicalDeviceVulkan13Features f13 = {VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_3_FEATURES};
  f13.dynamicRendering = VK_TRUE;
  VkPhysicalDeviceFeatures2 f2 = {VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2, &f13};
  VkDeviceCreateInfo dc = {VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, &f2, 0, 1, &dq};
  CK(CreateDevice(pd, &dc, 0, &dev));
  gdpa = (PFN_vkGetDeviceProcAddr)gipa(inst, "vkGetDeviceProcAddr");
  D(GetDeviceQueue); GetDeviceQueue(dev, qf, 0, &q);
  run_compute();
  run_scene();
  return 0;
}
