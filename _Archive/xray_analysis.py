import pandas as pd
# pyrefly: ignore [missing-import]
import numpy as np

def run_xray():
    df = pd.read_csv("backtest_v23_trades.csv")
    df['win'] = df['pnl_usd'] > 0
    df['loss'] = df['pnl_usd'] <= 0
    
    print("="*60)
    print("  DEEP X-RAY ANALYSIS RESULTS ")
    print("="*60)
    print(f"Total Trades: {len(df)}")
    print(f"Global Win Rate: {df['win'].mean() * 100:.2f}%")
    
    wins = df[df['win']]['pnl_usd'].sum()
    losses = abs(df[df['loss']]['pnl_usd'].sum())
    pf = wins / losses if losses > 0 else float('inf')
    print(f"Global Profit Factor: {pf:.2f}")
    print("-"*60)
    
    print("--- 1. BY SESSION ---")
    for session, group in df.groupby('session'):
        wr = group['win'].mean() * 100
        g_win = group[group['win']]['pnl_usd'].sum()
        g_loss = abs(group[group['loss']]['pnl_usd'].sum())
        pf_g = g_win / g_loss if g_loss > 0 else float('inf')
        print(f"{session:<15} | Trades: {len(group):<4} | WR: {wr:>5.1f}% | PF: {pf_g:.2f}")

    print("\n--- 2. BY RISK TIER ---")
    for tier, group in df.groupby('risk_tier'):
        wr = group['win'].mean() * 100
        g_win = group[group['win']]['pnl_usd'].sum()
        g_loss = abs(group[group['loss']]['pnl_usd'].sum())
        pf_g = g_win / g_loss if g_loss > 0 else float('inf')
        print(f"{tier:<15} | Trades: {len(group):<4} | WR: {wr:>5.1f}% | PF: {pf_g:.2f}")

    print("\n--- 3. BY PRICE ACTION ---")
    for pa, group in df.groupby('pa_pattern'):
        wr = group['win'].mean() * 100
        g_win = group[group['win']]['pnl_usd'].sum()
        g_loss = abs(group[group['loss']]['pnl_usd'].sum())
        pf_g = g_win / g_loss if g_loss > 0 else float('inf')
        print(f"{pa:<15} | Trades: {len(group):<4} | WR: {wr:>5.1f}% | PF: {pf_g:.2f}")

    print("\n--- 4. BY SCORE RANGE ---")
    bins = [0, 65, 75, 85, 100]
    labels = ['<65', '65-75', '75-85', '85+']
    df['score_bin'] = pd.cut(df['score'], bins=bins, labels=labels)
    for bin_val, group in df.groupby('score_bin'):
        if len(group) == 0: continue
        wr = group['win'].mean() * 100
        g_win = group[group['win']]['pnl_usd'].sum()
        g_loss = abs(group[group['loss']]['pnl_usd'].sum())
        pf_g = g_win / g_loss if g_loss > 0 else float('inf')
        print(f"Score {bin_val:<10} | Trades: {len(group):<4} | WR: {wr:>5.1f}% | PF: {pf_g:.2f}")
        
    print("\n--- 5. TOXIC COMBINATIONS (WR < 40%) ---")
    combos = df.groupby(['session', 'sweep_type']).agg(
        trades=('pnl_usd', 'count'),
        wins=('win', 'sum'),
        total_pnl=('pnl_usd', 'sum')
    )
    combos['wr'] = combos['wins'] / combos['trades'] * 100
    toxic = combos[(combos['wr'] < 40) & (combos['trades'] >= 5)]
    print(toxic)
    
if __name__ == '__main__':
    run_xray()
