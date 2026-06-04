# Security

`gdal-wheels` bundles GDAL + ~25 C libraries into each wheel, so its threat model
is supply-chain: known CVEs in bundled libs, a backdoored upstream release
(xz-style), a compromised CI action (tj-actions-style), and account/name takeover
on PyPI. As a heavily-used package this is a high-value target, so the defenses
below are layered.

## Automated (already in CI — no action needed)

- **CVE scanning of bundled native libs** — Syft SBOM + Trivy + Grype on the built
  wheel → GitHub Security tab; **weekly cron** re-scans against fresh feeds so a
  newly-disclosed CVE in a pinned dep turns red even with no code change
  (`.github/workflows/security.yml`).
- **Workflow auditing** — `zizmor` checks our workflows for injection, excessive
  permissions, and unpinned actions.
- **Runner hardening** — `step-security/harden-runner` audits build-time egress.
- **OpenSSF Scorecard** — posture grading → Security tab (`scorecard.yml`).
- **SLSA build provenance** — every wheel is attested (`actions/attest-build-provenance`);
  verify with `gh attestation verify <wheel> --repo taylor-geospatial/gdal-wheels`.
- **PEP 740 publish attestations** — enabled on the PyPI publish step (takes effect
  once Trusted Publishing is configured — see below).
- **Pinned third-party actions** (commit SHAs) + **Dependabot** to bump them.

## Operator setup — TODO (these require manual action and block full protection)

> These need owner/admin access to PyPI or the GitHub repo settings; CI cannot do
> them. Until done, the related automated piece is wired but inert.

- [ ] **PyPI: configure Trusted Publishing.** On pypi.org → the `gdal-wheels`
      project → *Publishing* → add a GitHub trusted publisher: owner
      `taylor-geospatial`, repo `gdal-wheels`, workflow `build-wheels.yaml`,
      environment `pypi`. **Blocks:** publishing + PEP 740 attestations.
- [ ] **PyPI: register the project name** `gdal-wheels`, and defensively register
      common typos (`gdalwheels`, `gdal_wheels`, `gdal-wheel`, `osgeo-gdal`).
      **Blocks:** name-squatting protection.
- [ ] **GitHub: create the `pypi` Environment** (Settings → Environments) with
      *required reviewers* so a human approves every PyPI publish.
- [ ] **GitHub: enable branch protection on `main`** — require PRs + passing
      status checks, block force-pushes (OpenSSF Scorecard flags this until set).
- [ ] **GitHub: enable secret scanning + push protection** (Settings → Code
      security & analysis).
- [ ] **StepSecurity: install the Harden-Runner GitHub App**, review the audited
      egress, then switch `egress-policy: audit` → `block` with an allowlist.
- [ ] *(optional, hardening)* Adopt **SLSA Level 3** via
      `slsa-framework/slsa-github-generator` for non-falsifiable provenance.

## Reporting a vulnerability

Open a private security advisory (Security tab → *Report a vulnerability*) or
email the maintainers. Please do not file public issues for vulnerabilities.
