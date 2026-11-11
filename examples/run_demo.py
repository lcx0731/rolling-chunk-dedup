"""Synthetic byte-level edit experiments; no external files or datasets."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import random

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from rolling_dedup import Config, chunks, spans, pack, unpack, inspect_archive


def compare(base, edited, config):
    old_blocks, new_blocks = chunks(base, config), chunks(edited, config)
    old_contents = set(old_blocks)
    reusable = sum(len(b) for b in new_blocks if b in old_contents)
    new_unique = set(new_blocks)-old_contents
    encoded = pack([base, edited], config)
    assert unpack(encoded) == [base, edited]
    accounting = inspect_archive(encoded)
    return {'config': asdict(config), 'base_chunks': len(old_blocks), 'edited_chunks': len(new_blocks),
            'edited_bytes': len(edited), 'reusable_edited_bytes': reusable,
            'reusable_edited_fraction': reusable/len(edited) if edited else 1.,
            'new_unique_payload_bytes': sum(map(len, new_unique)),
            'two_version_archive': accounting}


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20261110)
    base = rng.randbytes(128*1024)
    position, edit_size = len(base)//4, 101
    inserted = rng.randbytes(edit_size)
    edits = {'insert': base[:position]+inserted+base[position:],
             'delete': base[:position]+base[position+edit_size:],
             'overwrite': base[:position]+inserted+base[position+edit_size:],
             'append': base+inserted}
    cdc = Config()
    base_spans = spans(base, cdc)
    # Match the approximate baseline chunk count, not only a nominal mask size.
    fixed = Config(method='fixed', fixed_size=round(len(base)/len(base_spans)))
    configs = {'content_defined': cdc, 'fixed': fixed}
    cases = {name: {method: compare(base, edited, cfg) for method, cfg in configs.items()} for name, edited in edits.items()}
    repeated_block = rng.randbytes(8192)
    corpora = {'pseudorandom': base, 'repeated_8KiB': repeated_block*16, 'all_zero': bytes(len(base))}
    corpus_results = {}
    for name, data in corpora.items():
        corpus_results[name] = {}
        for method, cfg in configs.items():
            block_sizes = list(map(len, chunks(data, cfg)))
            encoded = pack([data], cfg)
            assert unpack(encoded) == [data]
            corpus_results[name][method] = {'sizes': block_sizes, 'mean_chunk_size': sum(block_sizes)/len(block_sizes),
                                           'max_size_chunk_fraction': sum(s == cfg.maximum for s in block_sizes)/len(block_sizes) if method == 'content_defined' else None,
                                           'archive': inspect_archive(encoded)}
    before = [end for _, end in base_spans]
    after = [end for _, end in spans(edits['insert'], cdc)]
    aligned_archive = pack([corpora['repeated_8KiB']], Config(method='fixed', fixed_size=8192))
    assert unpack(aligned_archive) == [corpora['repeated_8KiB']]
    summary = {'data': 'Deterministic synthetic bytes generated using Python random.Random(20261110). Not real files.',
               'base_size': len(base), 'edit_position': position, 'edit_size': edit_size,
               'configuration': {k: asdict(v) for k, v in configs.items()},
               'cases': cases, 'corpora': corpus_results,
               'aligned_fixed_8KiB_reference': inspect_archive(aligned_archive),
               'scope': 'Exact byte counts on these examples; no throughput or universal compression claims.'}
    (output/'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False)+'\n')
    (output/'insertion_boundaries.json').write_text(json.dumps({'position': position, 'insertion_size': edit_size, 'base_ends': before, 'edited_ends': after}, indent=2)+'\n')
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
    fig, axes = plt.subplots(2, 2, figsize=(12, 8.5), layout='constrained')
    fig.suptitle('Content-defined deduplication: edits, reuse, and overhead', fontsize=17, fontweight='bold')
    colors = {'content_defined': '#176885', 'fixed': '#b45822'}
    labels = {'content_defined': 'Content-defined', 'fixed': 'Fixed-size'}
    positions = np.arange(len(edits))
    ax = axes[0, 0]
    for j, method in enumerate(configs):
        ax.bar(positions+(j-.5)*.36, [cases[n][method]['reusable_edited_fraction']*100 for n in edits], .36, color=colors[method], label=labels[method])
    ax.set(xticks=positions, xticklabels=list(edits), ylim=(0, 120), yticks=[0,25,50,75,100], ylabel='Edited bytes in reusable chunks (%)', title='A. Reuse after a 101-byte edit')
    ax.legend(fontsize=9)
    ax = axes[0, 1]
    for j, method in enumerate(configs):
        ax.bar(positions+(j-.5)*.36, [cases[n][method]['new_unique_payload_bytes']/1024 for n in edits], .36, color=colors[method], label=labels[method])
    ax.set(xticks=positions, xticklabels=list(edits), ylabel='New unique payload (KiB)', title='B. Additional chunk content beyond the baseline')
    ax.legend(fontsize=9)
    ax = axes[1, 0]
    for j, method in enumerate(configs):
        ax.bar(np.arange(3)+(j-.5)*.36, [corpus_results[n][method]['archive']['archive_bytes']/len(base) for n in corpora], .36, color=colors[method], label=labels[method])
    ax.axhline(1, color='#666666', ls='--', lw=1, label='Raw input size')
    ax.set(xticks=range(3), xticklabels=['Pseudorandom', 'Repeated 8 KiB', 'All zero'], ylabel='Full archive / raw bytes', title='C. Metadata can outweigh payload savings')
    ax.legend(fontsize=9)
    ax = axes[1, 1]
    lo, hi = position-1000, position+5000
    old_visible = [x-position for x in before if lo <= x <= hi]
    # Align suffix coordinates by subtracting the insertion length.
    aligned_after = [x if x <= position else x-edit_size for x in after if x <= position or x >= position+edit_size]
    new_visible = [x-position for x in aligned_after if lo <= x <= hi]
    ax.eventplot([old_visible, new_visible], lineoffsets=[1, 0], linelengths=.5, colors=['#333333', '#176885'])
    ax.axvspan(0, 31, color='#d6c5e6', alpha=.7, label='31-byte window after edit')
    ax.set(yticks=[0,1], yticklabels=['Edited (suffix aligned)', 'Baseline'], xlabel='Aligned offset from insertion (bytes)', title='D. Local boundary alignment for this insertion', xlim=(-1000,5000), ylim=(-.6,1.6))
    ax.legend(fontsize=9, loc='upper right')
    fig.savefig(output/'dedup_audit.png', dpi=160)
    plt.close(fig)
    print(json.dumps({'baseline_cdc_chunks': len(base_spans), 'matched_fixed_size': fixed.fixed_size,
                      'insert_reuse_fraction': {m: cases['insert'][m]['reusable_edited_fraction'] for m in configs},
                      'insert_new_payload_bytes': {m: cases['insert'][m]['new_unique_payload_bytes'] for m in configs},
                      'pseudorandom_archive_ratio': {m: corpus_results['pseudorandom'][m]['archive']['archive_bytes']/len(base) for m in configs},
                      'all_zero_cdc_mean_chunk_size': corpus_results['all_zero']['content_defined']['mean_chunk_size']}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('results'))
    run(parser.parse_args().output)
