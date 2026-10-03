/*
 * Integration gate: the stack's unchanged Ipopt + a privately built libhsl.
 *
 * SCLS code, BSD-3-Clause-LBNL. Solves Hock-Schittkowski problem 71 through
 * Ipopt's public C interface (IpStdCInterface.h) with the linear solver and
 * HSL library given on the command line, and exits 0 only if Ipopt reports
 * success and the objective equals the known optimum 17.0140173 to 1e-6.
 *
 *   min  x1*x4*(x1+x2+x3) + x3
 *   s.t. x1*x2*x3*x4 >= 25,  x1^2+x2^2+x3^2+x4^2 = 40,  1 <= x <= 5
 *
 * Usage: ipopt_hs071 <linear_solver> [<path-to-libhsl.so>]
 * Build: cc ipopt_hs071.c -I<stack>/include/coin-or -L<stack>/lib -lipopt -lm
 */
#include <math.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include "IpStdCInterface.h"

static bool eval_f(ipindex n, ipnumber *x, bool new_x, ipnumber *obj, UserDataPtr u) {
    (void)n; (void)new_x; (void)u;
    *obj = x[0] * x[3] * (x[0] + x[1] + x[2]) + x[2];
    return true;
}
static bool eval_grad_f(ipindex n, ipnumber *x, bool new_x, ipnumber *g, UserDataPtr u) {
    (void)n; (void)new_x; (void)u;
    g[0] = x[0] * x[3] + x[3] * (x[0] + x[1] + x[2]);
    g[1] = x[0] * x[3];
    g[2] = x[0] * x[3] + 1.0;
    g[3] = x[0] * (x[0] + x[1] + x[2]);
    return true;
}
static bool eval_g(ipindex n, ipnumber *x, bool new_x, ipindex m, ipnumber *g, UserDataPtr u) {
    (void)n; (void)new_x; (void)m; (void)u;
    g[0] = x[0] * x[1] * x[2] * x[3];
    g[1] = x[0] * x[0] + x[1] * x[1] + x[2] * x[2] + x[3] * x[3];
    return true;
}
static bool eval_jac_g(ipindex n, ipnumber *x, bool new_x, ipindex m, ipindex nele,
                       ipindex *iRow, ipindex *jCol, ipnumber *v, UserDataPtr u) {
    (void)n; (void)new_x; (void)m; (void)nele; (void)u;
    if (v == NULL) {               /* dense 2x4 structure */
        for (int i = 0, k = 0; i < 2; i++)
            for (int j = 0; j < 4; j++, k++) { iRow[k] = i; jCol[k] = j; }
        return true;
    }
    v[0] = x[1] * x[2] * x[3]; v[1] = x[0] * x[2] * x[3];
    v[2] = x[0] * x[1] * x[3]; v[3] = x[0] * x[1] * x[2];
    v[4] = 2 * x[0]; v[5] = 2 * x[1]; v[6] = 2 * x[2]; v[7] = 2 * x[3];
    return true;
}
static bool eval_h(ipindex n, ipnumber *x, bool new_x, ipnumber of, ipindex m, ipnumber *lam,
                   bool new_lam, ipindex nele, ipindex *iRow, ipindex *jCol, ipnumber *v,
                   UserDataPtr u) {
    (void)n; (void)new_x; (void)m; (void)new_lam; (void)nele; (void)u;
    if (v == NULL) {               /* lower triangle, row-major */
        for (int i = 0, k = 0; i < 4; i++)
            for (int j = 0; j <= i; j++, k++) { iRow[k] = i; jCol[k] = j; }
        return true;
    }
    v[0] = of * 2 * x[3];                           /* (0,0) */
    v[1] = of * x[3];            v[2] = 0;          /* (1,0) (1,1) */
    v[3] = of * x[3];            v[4] = 0; v[5] = 0;                 /* (2,*) */
    v[6] = of * (2 * x[0] + x[1] + x[2]);           /* (3,0) */
    v[7] = of * x[0]; v[8] = of * x[0]; v[9] = 0;   /* (3,1) (3,2) (3,3) */
    /* constraint 1 */
    v[1] += lam[0] * x[2] * x[3];
    v[3] += lam[0] * x[1] * x[3]; v[4] += lam[0] * x[0] * x[3];
    v[6] += lam[0] * x[1] * x[2]; v[7] += lam[0] * x[0] * x[2]; v[8] += lam[0] * x[0] * x[1];
    /* constraint 2 */
    v[0] += lam[1] * 2; v[2] += lam[1] * 2; v[5] += lam[1] * 2; v[9] += lam[1] * 2;
    return true;
}

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: %s <linear_solver> [libhsl path]\n", argv[0]); return 2; }
    ipnumber x_L[4] = {1, 1, 1, 1}, x_U[4] = {5, 5, 5, 5};
    ipnumber g_L[2] = {25, 40}, g_U[2] = {2e19, 40};
    ipnumber x[4] = {1, 5, 5, 1}, g[2], mult_g[2], mult_xL[4], mult_xU[4], obj = 0;

    IpoptProblem nlp = CreateIpoptProblem(4, x_L, x_U, 2, g_L, g_U, 8, 10, 0,
                                          eval_f, eval_g, eval_grad_f, eval_jac_g, eval_h);
    if (!nlp) { fprintf(stderr, "CreateIpoptProblem failed\n"); return 1; }
    AddIpoptStrOption(nlp, "linear_solver", argv[1]);
    if (argc > 2) AddIpoptStrOption(nlp, "hsllib", argv[2]);
    AddIpoptNumOption(nlp, "tol", 1e-9);
    AddIpoptIntOption(nlp, "print_level", 3);

    enum ApplicationReturnStatus st = IpoptSolve(nlp, x, g, &obj, mult_g, mult_xL, mult_xU, NULL);
    FreeIpoptProblem(nlp);

    const double ref = 17.0140173;
    int ok = (st == Solve_Succeeded) && fabs(obj - ref) < 1e-6;
    printf("hs071 solver=%s status=%d objective=%.10f %s\n", argv[1], (int)st, obj,
           ok ? "OK" : "FAIL");
    return ok ? 0 : 1;
}
