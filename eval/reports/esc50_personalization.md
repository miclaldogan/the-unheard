| exemplars/class | top-1 | top-3 | macro-F1 (6 cls) | mean rank of truth | novel-flag known / unknown |
|---|---|---|---|---|---|
| 0 | 0.736 | 0.900 | 0.813 | 1.62 | 0.24 / 0.70 |
| 1 | 0.768 | 0.908 | 0.836 | 1.56 | 0.16 / 0.68 |
| 3 | 0.809 | 0.915 | 0.864 | 1.49 | 0.07 / 0.57 |
| 5 | 0.821 | 0.926 | 0.871 | 1.45 | 0.05 / 0.54 |

Per-class recall (n=0 → n=5): chirping_birds: 0.97→0.97, church_bells: 1.00→1.00, engine: 0.36→0.68, footsteps: 0.82→0.94, rain: 0.90→0.97, wind: 0.35→0.35

Unknown-class (wind, never taught) vs known: AUROC of nearest-exemplar cosine = 0.949 (n=5)

Novelty gate at n=5, novel = nearest<tau_n AND (margin<tau_m OR entropy>tau_e) — flag rate on known / unknown clips:
- tau_n=0.55,tau_m=0.6,tau_e=0.25: 0.05 / 0.54
- tau_n=0.55,tau_m=0.5,tau_e=0.3: 0.04 / 0.51
- tau_n=0.6,tau_m=0.6,tau_e=0.25: 0.07 / 0.62
- tau_n=0.5,tau_m=0.6,tau_e=0.25: 0.03 / 0.42
- tau_n=0.55,tau_m=1.0,tau_e=0.0: 0.08 / 0.80
- tau_n=0.55,tau_m=0.0,tau_e=1.0: 0.00 / 0.00
- medians known vs unknown: nearest cos 0.76 vs 0.44, fused margin 0.94 vs 0.42, base entropy 0.10 vs 0.35
