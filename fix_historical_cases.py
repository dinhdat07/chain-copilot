import pandas as pd

df = pd.read_csv("data/historical_cases.csv")

# Quick replacements in actions_taken and reflection_notes
replacements = {
    "R3": "R_HP_HN_MAIN",
    "R4": "R_BN_HN_ALT",
    "R1": "R_BN_HN_MAIN",
    "SUP_B": "SUP_HP",
    "SUP_D": "SUP_BD",
    "SUP_C": "SUP_QN",
    "SUP_A": "SUP_BN"
}

for i, row in df.iterrows():
    actions = row["actions_taken"]
    notes = row["reflection_notes"]
    if pd.notna(actions):
        for k, v in replacements.items():
            actions = actions.replace(k, v)
        df.at[i, "actions_taken"] = actions
        
    if pd.notna(notes):
        for k, v in replacements.items():
            notes = notes.replace(k, v)
        df.at[i, "reflection_notes"] = notes

df.to_csv("data/historical_cases.csv", index=False)
