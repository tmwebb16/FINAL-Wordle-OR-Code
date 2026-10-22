#include <stdint.h>
#include <string.h>
#include <stdlib.h>
#ifdef _WIN32
#define API __declspec(dllexport)
#else
#define API
#endif


API int last_best(const uint8_t *table, int stride, const int32_t *answers,
                  int n, const int32_t *rows, int m, int best, int *winner) {
    *winner = -1;
    uint32_t seen[243] = {0};
    for (int r = 0; r < m && best > 0; ++r) {
        uint32_t epoch = (uint32_t)r + 1;
        const uint8_t *row = table + (int64_t)rows[r] * stride;
        int failures = 0;
        for (int i = 0; i < n; ++i) {
            int code = row[answers[i]];
            if (seen[code] == epoch) { if (++failures >= best) break; }
            else seen[code] = epoch;
        }
        if (failures < best) { best = failures; *winner = rows[r]; }
    }
    return best;
}


API void partition(const uint8_t *row, const int32_t *answers, int n,
                   int32_t *output, int32_t *offsets) {
    int counts[243] = {0}, cursor[243];
    for (int i = 0; i < n; ++i) ++counts[row[answers[i]]];
    offsets[0] = 0;
    for (int k = 0; k < 243; ++k) {
        offsets[k+1] = offsets[k] + (k == 242 ? 0 : counts[k]);
        cursor[k] = offsets[k];
    }
    for (int i = 0; i < n; ++i) {
        int code = row[answers[i]];
        if (code != 242) output[cursor[code]++] = answers[i];
    }
}


API void rank_rows(const uint8_t *table, int stride, const int32_t *answers,
                   int n, const int32_t *rows, int m, int32_t *scores) {
    for (int r = 0; r < m; ++r) {
        int counts[243] = {0}, score = 0;
        const uint8_t *row = table + (int64_t)rows[r] * stride;
        for (int i = 0; i < n; ++i) {
            int code = row[answers[i]];
            score += 2 * counts[code]++ + 1;
        }
        scores[r] = score;
    }
}

typedef struct { uint64_t hash; int length; int32_t *data; } Signature;
typedef struct { Signature values[4096]; int slots[8192]; int used; } Context;

API void *second_context(void) { return calloc(1, sizeof(Context)); }

static void clear_context(Context *ctx) {
    for (int i = 0; i < ctx->used; ++i) free(ctx->values[i].data);
    memset(ctx->slots, 0, sizeof(ctx->slots));
    ctx->used = 0;
}

API void free_second_context(void *handle) {
    if (handle) { clear_context((Context *)handle); free(handle); }
}

static int duplicate(Context *ctx, int32_t *data, int length) {
    uint64_t hash = 1469598103934665603ULL;
    for (int i = 0; i < length; ++i) { hash ^= (uint32_t)data[i]; hash *= 1099511628211ULL; }
    if (ctx->used == 4096) clear_context(ctx);
    int slot = (int)(hash & 8191);
    while (ctx->slots[slot]) {
        Signature *s = &ctx->values[ctx->slots[slot] - 1];
        if (s->hash == hash && s->length == length && !memcmp(s->data, data, length * sizeof(int32_t)))
            return 1;
        slot = (slot + 1) & 8191;
    }
    int32_t *copy = malloc((length ? length : 1) * sizeof(int32_t));
    if (!copy) return 0;
    memcpy(copy, data, length * sizeof(int32_t));
    Signature *s = &ctx->values[ctx->used];
    s->hash = hash; s->length = length; s->data = copy;
    ctx->slots[slot] = ++ctx->used;
    return 0;
}

typedef int (*EvaluateChild)(const int32_t *, int, int);

API int second_best(const uint8_t *table, int stride, const int32_t *answers,
                    int n, const int32_t *rows, int m, int best,
                    EvaluateChild evaluate, void *handle, int *winner, int *completed) {
    *winner = -1; *completed = 0;
    int32_t *output = malloc((n ? n : 1) * sizeof(int32_t));
    int32_t *signature = malloc((n + 243) * sizeof(int32_t));
    if (!output || !signature) { free(output); free(signature); *completed = -1; return best; }
    for (int r = 0; r < m && best > 0; ++r) {
        const uint8_t *row = table + (int64_t)rows[r] * stride;
        int32_t offsets[244];
        partition(row, answers, n, output, offsets);
        int codes[242], count = 0, length = 0, lower = 0;
        for (int k = 0; k < 242; ++k) {
            int size = offsets[k+1] - offsets[k];
            if (size > 2) {
                int pos = count;
                while (pos > 0 && output[offsets[codes[pos-1]]] > output[offsets[k]]) {
                    codes[pos] = codes[pos-1]; --pos;
                }
                codes[pos] = k; ++count;
                if (size > 243) lower += size - 243;
            }
        }
        if (lower >= best) { *completed = r + 1; continue; }
        for (int j = 0; j < count; ++j) {
            int k = codes[j], size = offsets[k+1] - offsets[k];
            signature[length++] = size;
            memcpy(signature + length, output + offsets[k], size * sizeof(int32_t));
            length += size;
        }
        if (handle && duplicate((Context *)handle, signature, length)) {
            *completed = r + 1; continue;
        }
        for (int j = 1; j < count; ++j) {
            int k = codes[j], pos = j, size = offsets[k+1] - offsets[k];
            while (pos > 0 && offsets[codes[pos-1]+1] - offsets[codes[pos-1]] < size) {
                codes[pos] = codes[pos-1]; --pos;
            }
            codes[pos] = k;
        }
        int failures = 0;
        for (int j = 0; j < count && failures < best; ++j) {
            int k = codes[j], size = offsets[k+1] - offsets[k];
            int value = evaluate(output + offsets[k], size, best - failures);
            if (value < 0) { free(output); free(signature); return best; }
            failures += value;
        }
        if (failures < best) { best = failures; *winner = rows[r]; }
        *completed = r + 1;
    }
    free(output); free(signature);
    return best;
}
