# Legal Setup

This checklist is for turning the repository into a clean business asset.

## Current repo state

- The repository currently has a proprietary placeholder `LICENSE`.
- External contributions should not be accepted without a separate written
  agreement.
- The git history currently shows one commit author, but git history alone does
  not prove full ownership.
- The current licensing decision is to remain proprietary until the ownership
  and third-party inventory is complete.
- See `docs/THIRD_PARTY_INVENTORY.md` and `docs/DEPENDENCY_COMPLIANCE.md`.

## Ownership checklist

1. Identify the intended owner.
   - Decide whether the owner is you personally or a company/LLC.
   - If a company will own the IP, sign a written assignment into that entity.
2. Confirm authorship.
   - List everyone who wrote code, prompts, docs, graphics, or datasets.
   - Include contractors, friends, agencies, and AI-assisted sources where
     third-party material may have been copied in.
3. Inventory third-party material.
   - Review dependencies, copied snippets, images, icons, fonts, sample files,
     PDFs, docs, and training data.
   - Keep the source URL, upstream license, and usage rationale for each item.
   - Separate internal-use research inputs from material you plan to ship to
     customers.
4. Clean up contribution rights.
   - Get signed IP assignment agreements from any non-owner contributors.
   - Do not rely on verbal permission.
5. Decide distribution model.
   - Proprietary: keep the current no-public-license posture and use contracts
     for customers, evaluators, and contractors.
   - Open source: replace the placeholder `LICENSE` with a real open-source
     license after confirming you control all contributed material.
   - Current decision: proprietary until audit blockers are cleared.
6. Protect brand assets separately.
   - Domain names, logos, and product names are trademark issues, not just
     copyright issues.
   - Register the domain under the intended business owner.
7. Consider registration.
   - In the United States, copyright exists automatically.
   - Registration is still useful if you may need enforcement leverage.

## Recommended near-term actions

1. Create a contributor/source inventory in a private spreadsheet or Notion.
2. Move the intended business owner into an LLC or corporation if that is your
   plan.
3. Use written contractor and assignment paperwork before anyone else touches
   the code.
4. Replace placeholder secrets and admin credentials in deployment configs.
5. Ask counsel to review the final customer license, contractor assignment, and
   trademark/domain strategy before launch.
