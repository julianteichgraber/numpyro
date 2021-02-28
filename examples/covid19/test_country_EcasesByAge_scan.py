import numpy as np

from jax.lax import scan, cond, switch
import jax.numpy as jnp
import jax.ops as ops

import numpyro
from numpyro.util import identity

from functions import country_EcasesByAge


# direct implementation of country_EcasesByAge in NumPy with for loops
def country_EcasesByAge_direct(
    # parameters
    R0_local: float,
    e_cases_N0_local: float,
    log_relsusceptibility_age: jnp.float32,  # A
    impact_intv_children_effect: float,
    impact_intv_onlychildren_effect: float,
    impact_intv: jnp.float32,  # N2 x A
    # data
    N0: int,
    elementary_school_reopening_idx_local: int,
    N2: int,
    SCHOOL_STATUS_local: jnp.float32,  # N2
    A: int,
    A_CHILD: int,
    SI_CUT: int,
    wkend_idx_local, # boolean array
    avg_cntct_local: float,
    cntct_weekends_mean_local: jnp.float32,  # A x A
    cntct_weekdays_mean_local: jnp.float32,  # A x A
    cntct_school_closure_weekends_local: jnp.float32,  # A x A
    cntct_school_closure_weekdays_local: jnp.float32,  # A x A
    cntct_elementary_school_reopening_weekends_local: jnp.float32,  # A x A
    cntct_elementary_school_reopening_weekdays_local: jnp.float32,  # A x A
    rev_serial_interval: jnp.float32,  # SI_CUT
    popByAge_abs_local: jnp.float32,  # A
    N_init_A: int,
    init_A: jnp.int32,  # N_init_A
) -> jnp.float32:  # N2 x A

    # probability of infection given contact in location m
    rho0 = R0_local / avg_cntct_local

    # expected new cases by calendar day, age, and location under self-renewal model
    # and a container to store the precomputed cases by age
    E_casesByAge = np.zeros((N2, A))

    # init expected cases by age and location in first N0 days
    E_casesByAge[:N0, init_A] = e_cases_N0_local / N_init_A

    for t in range(N0, N2):
        start_idx_rev_serial = max(0, SI_CUT - t)
        start_idx_E_casesByAge = max(0, t - SI_CUT)

        prop_susceptibleByAge = 1.0 - E_casesByAge[:t].sum(0) / popByAge_abs_local
        prop_susceptibleByAge = np.maximum(0.0, prop_susceptibleByAge)

        tmp_row_vector_A = (rev_serial_interval[start_idx_rev_serial:SI_CUT][:, None] * E_casesByAge[start_idx_E_casesByAge:t]).sum(0)
        tmp_row_vector_A *= rho0
        tmp_row_vector_A_no_impact_intv = tmp_row_vector_A.copy()

        # choose weekend/weekday contact matrices
        weekend = wkend_idx_local[t - N0]  # this is a boolean
        cntct_mean_local = cntct_weekends_mean_local if weekend else cntct_weekdays_mean_local
        cntct_elementary_school_reopening_local = cntct_elementary_school_reopening_weekends_local if weekend \
                                             else cntct_elementary_school_reopening_weekdays_local
        cntct_school_closure_local = cntct_school_closure_weekends_local if weekend else cntct_school_closure_weekdays_local

        if SCHOOL_STATUS_local[t] == 0.0 and t < elementary_school_reopening_idx_local:  # school open
            col1 = (tmp_row_vector_A_no_impact_intv[:, None] * cntct_mean_local[:, :A_CHILD]).sum(0)
            col2 = (tmp_row_vector_A_no_impact_intv[:A_CHILD, None] * cntct_mean_local[:A_CHILD, A_CHILD:]).sum(0) +\
                    (tmp_row_vector_A[A_CHILD:, None] * cntct_mean_local[A_CHILD:, A_CHILD:]).sum(0) * impact_intv[t, A_CHILD:]
            E_casesByAge[t] = np.concatenate([col1, col2])
        elif SCHOOL_STATUS_local[t] == 0.0 and t >= elementary_school_reopening_idx_local:  # school reopen
            tmp_row_vector_A_with_children_impact_intv = tmp_row_vector_A.copy()
            tmp_row_vector_A_with_children_impact_intv[:A_CHILD] *= impact_intv_children_effect
            tmp_row_vector_A_with_children_and_childrenchildren_impact_intv = tmp_row_vector_A_with_children_impact_intv.copy()
            tmp_row_vector_A_with_children_and_childrenchildren_impact_intv[:A_CHILD] *= impact_intv_onlychildren_effect

            col1 = (tmp_row_vector_A_with_children_and_childrenchildren_impact_intv[:, None] *
                    cntct_elementary_school_reopening_local[:, :A_CHILD]).sum(0)
            col2 = (tmp_row_vector_A_with_children_impact_intv[:, None] *
                    cntct_elementary_school_reopening_local[:, A_CHILD:]).sum(0)
            E_casesByAge[t] = np.concatenate([col1, col2])

            E_casesByAge[t, :A_CHILD] *= impact_intv_children_effect
            E_casesByAge[t, A_CHILD:] *= impact_intv[t, A_CHILD:]
        else:  # school closed
            col1 = (tmp_row_vector_A_no_impact_intv[:, None] * cntct_school_closure_local[:, :A_CHILD]).sum(0)
            col2 = (tmp_row_vector_A_no_impact_intv[:A_CHILD, None] * cntct_school_closure_local[:A_CHILD, A_CHILD:]).sum(0) +\
                    (tmp_row_vector_A[A_CHILD:, None] * cntct_school_closure_local[A_CHILD:, A_CHILD:]).sum(0) * \
                     impact_intv[t, A_CHILD:]
            E_casesByAge[t] = np.concatenate([col1, col2])

        E_casesByAge[t] *= prop_susceptibleByAge
        E_casesByAge[t] *= np.exp(log_relsusceptibility_age)

    return E_casesByAge


if __name__ == '__main__':
    numpyro.enable_x64()

    NUM_TESTS = 6

    A = 6
    A_CHILD = 2
    N_init_A = 2
    init_A = [2, 4]

    for test in range(NUM_TESTS):
        N0 = 4 + 4 * test // 2
        N2 = 12 + 2 * test // 2
        SI_CUT = 9 + test

        R0_local = np.random.rand(1).item()
        e_cases_N0_local = np.random.rand(1).item()
        log_relsusceptibility_age = np.random.randn(A)
        impact_intv_children_effect = np.random.rand(1).item()
        impact_intv_onlychildren_effect = np.random.rand(1).item()
        impact_intv = np.random.rand(N2, A)
        elementary_school_reopening_idx_local = np.random.randint(N0 + 2, N0 + 6)
        SCHOOL_STATUS_local = np.array(np.random.randint(0, 2, N2), dtype=np.float32)
        avg_cntct_local = np.random.rand(1).item()
        wkend_idx_local = np.array(np.random.randint(0, 2, N2 - N0), dtype=np.bool)
        cntct_weekends_mean_local = np.random.rand(A, A)
        cntct_weekdays_mean_local = np.random.rand(A, A)
        cntct_school_closure_weekends_local = np.random.rand(A, A)
        cntct_school_closure_weekdays_local = np.random.rand(A, A)
        cntct_elementary_school_reopening_weekends_local = np.random.rand(A, A)
        cntct_elementary_school_reopening_weekdays_local = np.random.rand(A, A)
        rev_serial_interval = np.random.rand(SI_CUT)
        popByAge_abs_local = 12.3 * np.random.rand(A)

        value_direct = country_EcasesByAge_direct(
            R0_local,
            e_cases_N0_local,
            log_relsusceptibility_age,
            impact_intv_children_effect,
            impact_intv_onlychildren_effect,
            impact_intv,
            N0,
            elementary_school_reopening_idx_local,
            N2,
            SCHOOL_STATUS_local,
            A,
            A_CHILD,
            SI_CUT,
            wkend_idx_local,
            avg_cntct_local,
            cntct_weekends_mean_local,
            cntct_weekdays_mean_local,
            cntct_school_closure_weekends_local,
            cntct_school_closure_weekdays_local,
            cntct_elementary_school_reopening_weekends_local,
            cntct_elementary_school_reopening_weekdays_local,
            rev_serial_interval,
            popByAge_abs_local,
            N_init_A,
            init_A)

        value_scan = country_EcasesByAge(
            R0_local,
            e_cases_N0_local,
            log_relsusceptibility_age,
            impact_intv_children_effect,
            impact_intv_onlychildren_effect,
            jnp.array(impact_intv),
            N0,
            elementary_school_reopening_idx_local,
            N2,
            jnp.array(SCHOOL_STATUS_local),
            A,
            A_CHILD,
            SI_CUT,
            jnp.array(wkend_idx_local),
            avg_cntct_local,
            cntct_weekends_mean_local,
            cntct_weekdays_mean_local,
            cntct_school_closure_weekends_local,
            cntct_school_closure_weekdays_local,
            cntct_elementary_school_reopening_weekends_local,
            cntct_elementary_school_reopening_weekdays_local,
            rev_serial_interval,
            popByAge_abs_local,
            N_init_A,
            init_A)

        delta = value_direct - value_scan
        max_delta = np.max(np.fabs(delta))

        print("[Test {}] Max delta: {:.2e}".format(test, max_delta))
        assert value_direct.shape == (N2, A)
        assert value_scan.shape == (N2, A)
        assert max_delta < 1.0e-13