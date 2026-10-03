/*
 * Functional gate for HSL_MA77 in a privately built libcoinhsl (SCLS).
 *
 * SCLS code, BSD-3-Clause-LBNL. Contains no HSL source: it calls MA77's
 * documented C interface and is compiled against the licensee's own
 * hsl_ma77d.h from the assembled source tree at build time.
 *
 * Test 1: factor and solve a symmetric indefinite tridiagonal system
 *         A x = b with a known solution; check the forward error.
 * Test 2: the case HSL_MA77 6.5.0 fixed. Enter values that are not positive
 *         definite and factor with posdef = true, which must fail. Then
 *         enter positive definite values for the same pattern with
 *         input_reals, refactor, solve, and check the forward error.
 *
 * Usage: ma77_factor_solve <scratch-dir>   (MA77 writes its out-of-core files
 *        there). Exit 0 on success.
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "hsl_ma77d.h"

#define N 40
#define TOL 1e-10

static char fname[4][4096];

/* Row i of a tridiagonal matrix, 0-based: diagonal d[i], off-diagonals e. */
static int row(int i, double diag, double off, int idx[3], double val[3]) {
    int k = 0;
    if (i > 0)     { idx[k] = i - 1; val[k++] = off; }
    idx[k] = i; val[k++] = diag;
    if (i < N - 1) { idx[k] = i + 1; val[k++] = off; }
    return k;
}

static double diag_indef(int i) { return (i % 2) ? -4.0 : 4.0; }
static double diag_posdef(int i) { (void)i; return 4.0; }
static double diag_notposdef(int i) { return (i == N / 2) ? -4.0 : 4.0; }

static int solve_and_check(void **keep, struct ma77_control *control,
                           struct ma77_info *info, double (*diag)(int),
                           double off, const char *label) {
    double x[N], xt[N], err = 0.0;
    for (int i = 0; i < N; i++) xt[i] = 1.0 + (double)i / N;
    for (int i = 0; i < N; i++) {
        x[i] = diag(i) * xt[i];
        if (i > 0) x[i] += off * xt[i - 1];
        if (i < N - 1) x[i] += off * xt[i + 1];
    }
    ma77_solve(0, 1, N, x, keep, control, info, NULL);
    if (info->flag < 0) {
        fprintf(stderr, "%s: ma77_solve flag %d\n", label, info->flag);
        return 1;
    }
    for (int i = 0; i < N; i++) {
        double e = fabs(x[i] - xt[i]) / fabs(xt[i]);
        if (!isfinite(e)) err = INFINITY;   /* NaN/Inf in the solution is a failure */
        else if (e > err) err = e;
    }
    printf("%s: max relative forward error %.3e\n", label, err);
    return !(err <= TOL);
}

static int enter_matrix(void **keep, struct ma77_control *control,
                        struct ma77_info *info, double (*diag)(int), double off,
                        int with_vars) {
    int idx[3];
    double val[3];
    for (int i = 0; i < N; i++) {
        int k = row(i, diag(i), off, idx, val);
        if (with_vars) {
            ma77_input_vars(i, k, idx, keep, control, info);
            if (info->flag < 0) {
                fprintf(stderr, "ma77_input_vars row %d flag %d\n", i, info->flag);
                return 1;
            }
        }
        ma77_input_reals(i, k, val, keep, control, info);
        if (info->flag < 0) {
            fprintf(stderr, "ma77_input_reals row %d flag %d\n", i, info->flag);
            return 1;
        }
    }
    return 0;
}

static int open_and_analyse(void **keep, struct ma77_control *control,
                            struct ma77_info *info, double (*diag)(int), double off) {
    int order[N];
    ma77_open(N, fname[0], fname[1], fname[2], fname[3], keep, control, info);
    if (info->flag < 0) {
        fprintf(stderr, "ma77_open flag %d\n", info->flag);
        return 1;
    }
    if (enter_matrix(keep, control, info, diag, off, 1)) return 1;
    for (int i = 0; i < N; i++) order[i] = i;
    ma77_analyse(order, keep, control, info);
    if (info->flag < 0) {
        fprintf(stderr, "ma77_analyse flag %d\n", info->flag);
        return 1;
    }
    return 0;
}

int main(int argc, char **argv) {
    const char *dir = argc > 1 ? argv[1] : ".";
    /* MA77 is out-of-core: it keeps its factors in four direct-access files
     * named by the caller. These names are ours; any four distinct names work. */
    const char *base[4] = {"scls_ma77_int", "scls_ma77_real", "scls_ma77_work", "scls_ma77_tmp"};
    for (int i = 0; i < 4; i++)
        snprintf(fname[i], sizeof fname[i], "%s/%s", dir, base[i]);

    void *keep = NULL;
    struct ma77_control control;
    struct ma77_info info;
    int failed = 0;

    /* Test 1: indefinite factor + solve. */
    ma77_default_control(&control);
    if (open_and_analyse(&keep, &control, &info, diag_indef, 1.0)) return 1;
    ma77_factor(0, &keep, &control, &info, NULL);
    if (info.flag < 0) {
        fprintf(stderr, "test 1: ma77_factor flag %d\n", info.flag);
        return 1;
    }
    failed |= solve_and_check(&keep, &control, &info, diag_indef, 1.0, "test 1 (indefinite)");
    ma77_finalise(&keep, &control, &info);

    /* Test 2: posdef factor of a non-posdef matrix must fail; then new
     * values via input_reals, refactor and solve must succeed. */
    ma77_default_control(&control);
    if (open_and_analyse(&keep, &control, &info, diag_notposdef, 1.0)) return 1;
    ma77_factor(1, &keep, &control, &info, NULL);
    if (info.flag >= 0) {
        fprintf(stderr, "test 2: posdef factor of a non-posdef matrix did not fail (flag %d)\n",
                info.flag);
        failed = 1;
    } else {
        printf("test 2: first factor failed as expected (flag %d)\n", info.flag);
    }
    if (enter_matrix(&keep, &control, &info, diag_posdef, 1.0, 0)) {
        fprintf(stderr, "test 2: input_reals after the failed factor was rejected\n");
        ma77_finalise(&keep, &control, &info);
        return 1;
    }
    ma77_factor(1, &keep, &control, &info, NULL);
    if (info.flag < 0) {
        fprintf(stderr, "test 2: refactor flag %d\n", info.flag);
        ma77_finalise(&keep, &control, &info);
        return 1;
    }
    failed |= solve_and_check(&keep, &control, &info, diag_posdef, 1.0, "test 2 (refactor)");
    ma77_finalise(&keep, &control, &info);

    puts(failed ? "MA77 functional gate: FAIL" : "MA77 functional gate: PASS");
    return failed;
}
