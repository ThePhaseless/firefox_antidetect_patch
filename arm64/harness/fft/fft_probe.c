// SPDX-License-Identifier: 0BSD
// Runs ffvpx's av_tx the way dom/media/webaudio/FFTBlock.h does (AV_TX_FLOAT_RDFT, forward
// and inverse, stride 2*sizeof(float), flags 0) for every power of two from 4 to 262144
// (WebAudio uses 32 to 32768; the rest is the codelets' whole range), and as an in-place
// complex FFT (AV_TX_FLOAT_FFT with AV_TX_INPLACE), which is how the pre-shuffled codelets
// get picked. Writes the output bits to <out>/<variant>/<kind>-<dir>-<n>-<signal>.bin.
// stdout carries the CPU flags and the transform tree libavutil picked.
//   fft_probe <out> [variant ...]
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include "config.h"
#include "libavutil/cpu.h"
#include "libavutil/log.h"
#include "libavutil/tx.h"

// log.c is not linked: tx.c prints its transform tree through this at AV_LOG_DEBUG.
void av_log(void *avcl, int level, const char *fmt, ...) {
  if (level > AV_LOG_DEBUG) return;
  va_list ap;
  va_start(ap, fmt);
  vprintf(fmt, ap);
  va_end(ap);
}

struct variant {
  const char *name;
  int need, set, clear;  // host flags it needs, then adds and removes; clear -1 = no asm
  int host;              // leave the detected flags alone
};

static const struct variant variants[] = {
    {"host", 0, 0, 0, 1},
#if ARCH_X86
    {"avx2", AV_CPU_FLAG_AVX2 | AV_CPU_FLAG_FMA3, 0, AV_CPU_FLAG_AVXSLOW | AV_CPU_FLAG_SLOW_GATHER, 0},
    {"avx2-slow-gather", AV_CPU_FLAG_AVX2 | AV_CPU_FLAG_FMA3, AV_CPU_FLAG_SLOW_GATHER, AV_CPU_FLAG_AVXSLOW, 0},
    {"fma3", AV_CPU_FLAG_FMA3, 0, AV_CPU_FLAG_AVX2 | AV_CPU_FLAG_AVX512 | AV_CPU_FLAG_AVX512ICL | AV_CPU_FLAG_AVXSLOW | AV_CPU_FLAG_SLOW_GATHER, 0},
    {"avx", AV_CPU_FLAG_AVX, 0, AV_CPU_FLAG_FMA3 | AV_CPU_FLAG_AVX2 | AV_CPU_FLAG_AVX512 | AV_CPU_FLAG_AVX512ICL | AV_CPU_FLAG_AVXSLOW | AV_CPU_FLAG_SLOW_GATHER, 0},
#endif
    {"c", 0, 0, -1, 0},
};

static uint32_t lcg;
static float rnd(void) {
  lcg = lcg * 1664525u + 1013904223u;
  return (float)(int32_t)lcg / 2147483648.0f;
}

// No libm here: every input value is the same bits on every host.
static void fill(float *buf, int n, int inv, int sig) {
  int count = inv ? n + 2 : n;
  memset(buf, 0, sizeof(float) * (n + 2));
  if (sig == 0) {  // noise
    lcg = 0x9e3779b9u ^ (uint32_t)n ^ (uint32_t)inv;
    for (int i = 0; i < count; i++) buf[i] = rnd();
    if (inv) buf[1] = buf[n + 1] = 0.0f;  // DC and Nyquist are real
  } else if (!inv) {  // a ramp, as an oscillator's sawtooth
    for (int i = 0; i < n; i++) buf[i] = (float)((i * 37) % n) / (float)n * 2.0f - 1.0f;
  } else {  // PeriodicWave's sawtooth: imaginary 1/k with alternating sign
    for (int k = 1; k < n / 2; k++) buf[2 * k + 1] = (k & 1 ? 1.0f : -1.0f) / (float)k;
  }
}

static int run(const char *out, const struct variant *v, int host) {
  char path[4096];
  int flags = v->host ? host : v->clear == -1 ? 0 : (host | v->set) & ~v->clear;
  if ((host & v->need) != v->need) {
    printf("variant %s skipped: host flags 0x%x lack 0x%x\n", v->name, host, v->need & ~host);
    return 0;
  }
  av_force_cpu_flags(v->host ? -1 : flags);
  printf("variant %s flags 0x%x (host 0x%x)\n", v->name, av_get_cpu_flags(), host);
  snprintf(path, sizeof(path), "%s/%s", out, v->name);
  mkdir(path, 0777);
  for (int kind = 0; kind < 2; kind++) {  // 0: FFTBlock's RDFT, 1: in-place complex FFT
    // the in-place map costs O(n^2) to build: 8192 still reaches every pre-shuffled codelet
    for (int n = 4; n <= (kind ? 8192 : 262144); n *= 2) {
      for (int inv = 0; inv < 2; inv++) {
        AVTXContext *ctx = NULL;
        av_tx_fn fn = NULL;
        float scale = 1.0f;
        const char *k = kind ? "fft" : "rdft", *d = inv ? "inverse" : "forward";
        printf("%s %s %s n=%d\n", v->name, k, d, n);
        if (av_tx_init(&ctx, &fn, kind ? AV_TX_FLOAT_FFT : AV_TX_FLOAT_RDFT, inv, kind ? n / 2 : n, &scale,
                       kind ? AV_TX_INPLACE : 0)) {
          fprintf(stderr, "av_tx_init failed: %s %s n=%d inv=%d\n", v->name, k, n, inv);
          return 1;
        }
        for (int sig = 0; sig < 2 - kind; sig++) {
          // 64-byte aligned like AlignedTArray's buffers (the x86 codelets use aligned stores)
          size_t bytes = sizeof(float) * (n + 64);
          float *in = aligned_alloc(64, bytes), *dst = aligned_alloc(64, bytes);
          // floats out: n samples, n/2+1 complex bins, or the n/2 complex values of the FFT
          size_t outn = kind || inv ? n : n + 2;
          FILE *f;
          if (!in || !dst) return 1;
          memset(dst, 0, bytes);
          fill(in, n, kind ? 0 : inv, sig);
          if (kind)
            fn(ctx, in, in, 2 * sizeof(float));
          else
            fn(ctx, dst, in, 2 * sizeof(float));
          snprintf(path, sizeof(path), "%s/%s/%s-%s-%06d-%s.bin", out, v->name, k, d, n, sig ? "saw" : "noise");
          if (!(f = fopen(path, "wb")) || fwrite(kind ? in : dst, sizeof(float), outn, f) != outn || fclose(f)) {
            perror(path);
            return 1;
          }
          free(in);
          free(dst);
        }
        av_tx_uninit(&ctx);
      }
    }
  }
  return 0;
}

int main(int argc, char **argv) {
  int host = av_get_cpu_flags(), seen = 0;
  if (argc < 2) {
    fprintf(stderr, "usage: fft_probe <out> [variant ...]\n");
    return 2;
  }
  for (size_t i = 0; i < sizeof(variants) / sizeof(*variants); i++) {
    int want = argc == 2;
    for (int a = 2; a < argc; a++) want |= !strcmp(argv[a], variants[i].name);
    if (!want) continue;
    seen++;
    if (run(argv[1], &variants[i], host)) return 1;
  }
  if (!seen) {
    fprintf(stderr, "no such variant\n");
    return 2;
  }
  return 0;
}
