"""HELENA quantitative reproduction, version 1.0.0.

Run: python analysis/analyze.py --output /tmp/helena-statistics.json
Install: python -m pip install -r analysis/requirements.txt
Reads only the public per-participant TXT files. No network or API calls.
This publication adaptation is not evidence of a pre-study script freeze.
"""
from pathlib import Path
from collections import Counter
import argparse, hashlib, json, math, importlib.metadata, types
import numpy as np
from scipy import stats, special, optimize
import statsmodels.api as sm
ANALYSIS_VERSION = 'helena-txt-1.0.0'

CONSTRUCTS = {
    'usefulness': ('usefulness_ideal', 'usefulness_find_easy', 'usefulness_suggestions'),
    'control': ('control_preferences', 'control_recommendations', 'control_adjustment'),
    'transparency': ('transparency_why', 'transparency_assessment', 'transparency_fit'),
    'trust': ('trust_fit', 'trust_credibility'),
}

SINGLES = ('dialogue_understanding', 'dialogue_response_quality', 'dialogue_attentiveness',
           'overall_satisfaction', 'intention_reuse', 'study_effort', 'study_style_control',
           'perceived_character')

ARMS = ('A', 'B', 'C')

def answer(row, name):
    nested = row.get('answers') or {}
    return nested.get(name, row.get('v14_' + name, row.get(name)))

def rating(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number.is_integer() and 1 <= number <= 7 else None

def _safe(value):
    return float(value) if value is not None and math.isfinite(float(value)) else None

def complete_items(row, construct):
    values = [rating(answer(row, field)) for field in CONSTRUCTS[construct]]
    return values if all(value is not None for value in values) else None

def describe(values):
    values = np.asarray(values, dtype=float)
    return {'n': len(values), 'mean': _safe(np.mean(values)) if len(values) else None,
            'sd': _safe(np.std(values, ddof=1)) if len(values) > 1 else None,
            'median': _safe(np.median(values)) if len(values) else None}

def _hedges(first, second, axis=None):
    n1, n2 = first.shape[-1], second.shape[-1]
    df = n1 + n2 - 2
    pooled = ((n1 - 1) * np.var(first, axis=axis, ddof=1) +
              (n2 - 1) * np.var(second, axis=axis, ddof=1)) / df
    correction = math.exp(special.gammaln(df / 2) - .5 * math.log(df / 2) - special.gammaln((df - 1) / 2))
    with np.errstate(divide='ignore', invalid='ignore'):
        return correction * (np.mean(first, axis=axis) - np.mean(second, axis=axis)) / np.sqrt(pooled)

def compare(first, second, *, comparison_id='', construct='', contrast='', bootstrap_samples=5000):
    first, second = np.asarray(first, dtype=float), np.asarray(second, dtype=float)
    d1, d2 = describe(first), describe(second)
    out = {'id': comparison_id, 'construct': construct, 'contrast': contrast,
           'n_first': d1['n'], 'n_second': d2['n'], 'mean_first': d1['mean'], 'mean_second': d2['mean'],
           'sd_first': d1['sd'], 'sd_second': d2['sd'], 'difference': None, 'difference_ci95': None,
           'statistic': None, 'df': None, 'p_value': None, 'hedges_g': None, 'hedges_g_ci95': None,
           'mann_whitney_p': None, 'levene_p_diagnostic_only': None, 'status': 'insufficient_data',
           'method': 'two-sided Welch t-test; no variance-test-based selection',
           'g_ci_method': 'independent-group percentile bootstrap, deterministic seed, 5000 replicates'}
    if min(len(first), len(second)) < 2:
        return out
    out['difference'] = float(np.mean(first) - np.mean(second))
    a, b = np.var(first, ddof=1) / len(first), np.var(second, ddof=1) / len(second)
    if a + b <= 0:
        out['status'] = 'zero_variance'
        return out
    df = (a + b) ** 2 / (a * a / (len(first) - 1) + b * b / (len(second) - 1))
    se = math.sqrt(a + b)
    half = stats.t.ppf(.975, df) * se
    statistic = out['difference'] / se
    out.update(status='ok', statistic=_safe(statistic), df=_safe(df),
               p_value=_safe(2 * stats.t.sf(abs(statistic), df)),
               difference_ci95=[float(out['difference'] - half), float(out['difference'] + half)],
               hedges_g=_safe(_hedges(first, second)))
    if bootstrap_samples and out['hedges_g'] is not None:
        seed = int(hashlib.sha256((comparison_id + ':' + construct + ':' + contrast).encode()).hexdigest()[:8], 16)
        rng = np.random.default_rng(seed)
        samples = _hedges(rng.choice(first, (bootstrap_samples, len(first))),
                          rng.choice(second, (bootstrap_samples, len(second))), axis=1)
        valid = samples[np.isfinite(samples)]
        # Do not conceal degenerate bootstrap draws in very small/discrete samples.
        out['g_ci_valid_replicates'] = len(valid)
        out['g_ci_replicates'] = bootstrap_samples
        out['g_ci_method'] = f'independent-group percentile bootstrap, deterministic seed, {bootstrap_samples} replicates'
        if len(valid) >= .99 * bootstrap_samples:
            out['hedges_g_ci95'] = [float(x) for x in np.quantile(valid, [.025, .975])]
        else:
            out['g_ci_warning'] = 'Over 1% zero-variance bootstrap draws; interval not reported.'
    out['mann_whitney_p'] = _safe(stats.mannwhitneyu(first, second, alternative='two-sided', method='asymptotic').pvalue)
    # Levene is diagnostic only; Welch is used regardless of this value.
    deviations = [np.abs(x - np.median(x)) for x in (first, second)]
    if any(np.var(x) > 0 for x in deviations):
        out['levene_p_diagnostic_only'] = _safe(stats.levene(first, second, center='median').pvalue)
    return out

def holm(p_values):
    """Keep the prespecified family size even if one test is not estimable."""
    adjusted = [None] * len(p_values)
    ordered = sorted((float(p), i) for i, p in enumerate(p_values) if p is not None)
    prior = 0.0
    for rank, (p, index) in enumerate(ordered):
        prior = max(prior, (len(p_values) - rank) * p)
        adjusted[index] = min(1.0, prior)
    return adjusted

def reliability(rows, construct):
    items = [values for row in rows if (values := complete_items(row, construct)) is not None]
    out = {'n': len(items), 'items': len(CONSTRUCTS[construct]), 'alpha': None,
           'status': 'insufficient_data', 'interpretation': 'Reliability does not establish construct validity.'}
    if len(items) < 2:
        return out
    matrix = np.asarray(items, dtype=float)
    total_variance = np.var(matrix.sum(axis=1), ddof=1)
    k = matrix.shape[1]
    if total_variance <= 0:
        out['status'] = 'zero_total_variance'
        return out
    out['alpha'] = _safe(k / (k - 1) * (1 - np.var(matrix, axis=0, ddof=1).sum() / total_variance))
    out['status'] = 'ok'
    out['below_point_seven'] = out['alpha'] < .7
    if k == 2:
        if all(np.var(matrix[:, i]) > 0 for i in range(k)):
            r = _safe(np.corrcoef(matrix.T)[0, 1])
            out['inter_item_correlation'] = r
            out['spearman_brown'] = _safe(2 * r / (1 + r)) if r > -1 else None
        out['interpretation'] = 'Adapted two-item trust pair; alpha and Spearman–Brown are descriptive, not a validation.'
    return out

RATING_ITEMS = tuple(i for items in CONSTRUCTS.values() for i in items) + SINGLES + ('postings_available',)
core = types.SimpleNamespace(**{name: globals()[name] for name in ['CONSTRUCTS','SINGLES','compare','holm','describe','reliability']})

def load(root):
    ROOT = root
    rows = []
    digest = hashlib.sha256()
    for folder in sorted((ROOT/'participants').iterdir()):
        if not folder.is_dir():
            continue
        row = {'id': folder.name, 'answers': {}}
        for file in sorted(folder.glob('*/answer.txt')):
            raw = file.read_bytes()
            digest.update(file.relative_to(ROOT).as_posix().encode()+b'\0'+raw+b'\0')
            value = raw.decode('utf-8').rstrip('\n')
            name = file.parent.name
            if name == 'condition':
                assert value in ('A', 'B', 'C')
                row['condition'] = value
            elif name != 'feedback':
                row['answers'][name] = None if value == 'MISSING' else int(value)
            else:
                row['has_feedback'] = value != 'MISSING'
        expected=set(RATING_ITEMS)|{'job_portal_experience','ai_chat_experience'}
        if set(row['answers']) != expected or row.get('condition') not in ARMS:
            raise ValueError(f'Unexpected or missing fields in {folder.name}')
        for name,value in row['answers'].items():
            allowed=range(1,8) if name in RATING_ITEMS else range(4)
            if value is not None and value not in allowed:
                raise ValueError(f'Invalid response: {folder.name}/{name}')
        for construct, items in core.CONSTRUCTS.items():
            values = [row['answers'][item] for item in items]
            row['answers'][construct] = None if None in values else float(np.mean(values))
        rows.append(row)
    return rows, digest.hexdigest()

def vals(rows, field):
    return np.array([r['answers'][field] for r in rows if r['answers'].get(field) is not None], float)

def compare(rows, field, first, second, name='exploratory'):
    return core.compare(vals([r for r in rows if r['condition']==first],field),
                            vals([r for r in rows if r['condition']==second],field),
                            comparison_id=name,construct=field,contrast=first+'-'+second)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, help='Optional JSON output; otherwise print to stdout')
    args = parser.parse_args()
    rows, digest = load(args.root)
    groups = {a:[r for r in rows if r['condition']==a] for a in 'ABC'}
    result = {'provenance':{'method':'Retrospective reproduction from per-question TXT files',
                           'response_files_sha256':digest,
                           'analysis_version': ANALYSIS_VERSION,
                           'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                           'dependencies': {m: importlib.metadata.version(m) for m in ['numpy','scipy','statsmodels']},
                           'scope': 'Reproduction release; does not establish historical use or preregistration. Dropout records and qualitative category assignments are not in the public data.'},
              'sample':dict(Counter(r['condition'] for r in rows)),
              'feedback_counts':{a:sum(r['has_feedback'] for r in rs) for a,rs in groups.items()},
              'descriptive':{}, 'pairwise':{}, 'reliability':{}, 'correlations':{}}
    fields = list(core.CONSTRUCTS)+list(core.SINGLES)+['postings_available']
    result['H1'] = compare(rows,'usefulness','C','B','H1')
    secondary = [compare(rows,'control','C','B','S1'),compare(rows,'transparency','C','B','S2'),compare(rows,'usefulness','B','A','S3')]
    for test,p in zip(secondary,core.holm([t['p_value'] for t in secondary])):
        test['p_holm']=p
    result['secondary']=secondary
    for field in fields:
        result['descriptive'][field]={a:core.describe(vals(rs,field)) for a,rs in groups.items()}
        result['pairwise'][field]=[compare(rows,field,a,b) for a,b in [('C','B'),('B','A'),('C','A')]]
    result['usefulness_items']={item:[compare(rows,item,a,b) for a,b in [('C','B'),('B','A')]] for item in core.CONSTRUCTS['usefulness']}
    for construct in core.CONSTRUCTS:
        result['reliability'][construct]={a:core.reliability(rs,construct) for a,rs in {'all':rows,**groups}.items()}
    for arm,rs in groups.items():
        result['correlations'][arm]={}
        for field in fields:
            pair=[(r['answers']['usefulness'],r['answers'][field]) for r in rs if r['answers']['usefulness'] is not None and r['answers'][field] is not None]
            rho,p=stats.spearmanr(np.asarray(pair)[:,0],np.asarray(pair)[:,1])
            result['correlations'][arm][field]={'n':len(pair),'rho':float(rho),'p':float(p)}
    kw=stats.kruskal(*[vals(groups[a],'perceived_character') for a in 'ABC'])
    result['character_kruskal']={'H':float(kw.statistic),'p':float(kw.pvalue)}
    result['usefulness_distribution']={}
    for a,rs in groups.items():
        v=vals(rs,'usefulness')
        result['usefulness_distribution'][a]={'n':len(v),'below4':int(sum(v<4)),'4_to_below6':int(sum((v>=4)&(v<6))),'at_least6':int(sum(v>=6))}
    result['availability_subgroups']={}
    for label,upper in [('low',False),('high',True)]:
        subset=[r for r in rows if r['answers']['postings_available'] is not None and (r['answers']['postings_available']>=5)==upper]
        result['availability_subgroups'][label]={'descriptive':{a:core.describe(vals([r for r in subset if r['condition']==a],'usefulness')) for a in 'ABC'},'C-B':compare(subset,'usefulness','C','B'),'B-A':compare(subset,'usefulness','B','A')}
    regression=[r for r in rows if all(r['answers'].get(k) is not None for k in ['usefulness','job_portal_experience','ai_chat_experience'])]
    x=[[1,int(r['condition']=='A'),int(r['condition']=='C'),r['answers']['job_portal_experience'],r['answers']['ai_chat_experience']] for r in regression]
    fit=sm.OLS([r['answers']['usefulness'] for r in regression],x).fit(cov_type='HC3')
    result['experience_adjustment_HC3']={'n':len(regression),'terms':{name:{'b':float(b),'p':float(p),'ci95':list(map(float,ci))} for name,b,p,ci in zip(['intercept_B','A_minus_B','C_minus_B','job_portal_experience','ai_chat_experience'],fit.params,fit.pvalues,fit.conf_int())}}
    result['experience_tables']={}
    for field in ['job_portal_experience','ai_chat_experience']:
        table=[[int(sum(r['answers'][field]==v for r in groups[a])) for v in range(4)] for a in 'ABC']
        chi,p,dof,_=stats.chi2_contingency(table)
        result['experience_tables'][field]={'rows':'ABC','columns':[0,1,2,3],'counts':table,'chi2':float(chi),'df':int(dof),'p':float(p)}
    result['missing_ratings']={field:{a:sum(r['answers'][field] is None for r in rs) for a,rs in groups.items()} for field in RATING_ITEMS}
    result['effort_equivalence']={}
    for second in 'AB':
        c=compare(rows,'study_effort','C',second)
        se=c['difference']/c['statistic']
        result['effort_equivalence'][second]={}
        for margin in [.5,.75]:
            p=max(stats.t.sf((c['difference']+margin)/se,c['df']),stats.t.cdf((c['difference']-margin)/se,c['df']))
            half=stats.t.ppf(.95,c['df'])*se
            result['effort_equivalence'][second][str(margin)]={'p':float(p),'difference':c['difference'],'ci90':[c['difference']-half,c['difference']+half]}
    subset=[r for r in rows if r['condition'] in 'BC' and all(r['answers'].get(k) is not None for k in ['usefulness','postings_available'])]
    x=[[1,int(r['condition']=='C'),int(r['answers']['postings_available']>=5),int(r['condition']=='C')*int(r['answers']['postings_available']>=5)] for r in subset]
    fit=sm.OLS([r['answers']['usefulness'] for r in subset],x).fit(cov_type='HC3')
    result['availability_interaction_HC3']={'n':len(subset),'terms':{name:{'b':float(b),'p':float(p),'se':float(se)} for name,b,p,se in zip(['intercept_B_low','C_minus_B_low','high_minus_low_B','interaction'],fit.params,fit.pvalues,fit.bse)}}
    n1=len(vals(groups['C'],'usefulness'));n2=len(vals(groups['B'],'usefulness'))
    def power(d):
        df=n1+n2-2;critical=stats.t.ppf(.975,df);ncp=d/math.sqrt(1/n1+1/n2)
        return float(stats.nct.sf(critical,df,ncp)+stats.nct.cdf(-critical,df,ncp))
    result['sensitivity_power']={'method':'noncentral t, equal-variance benchmark; not exact Welch power','detectable_d_80_percent':float(optimize.brentq(lambda d:power(d)-.8,.001,1)),'power_d_035':power(.35)}
    payload=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    if args.output:
        if args.output.resolve().is_relative_to((args.root/'participants').resolve()):
            raise ValueError('Output must not overwrite participant data.')
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(payload,encoding='utf-8')
    else:
        print(payload,end='')

if __name__=='__main__':
    main()
