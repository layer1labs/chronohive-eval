# Terms of Confidentiality — ChronoHive Evaluation

> **DRAFT — REQUIRES REVIEW BY LEGAL COUNSEL BEFORE USE.**
> This document is a template. It is not legal advice and creates no
> attorney-client relationship. Have counsel review and adapt it before
> any evaluator executes it.

**CONFIDENTIAL — DO NOT DISTRIBUTE**

© 2026 Layer1Labs Silicon Inc. All rights reserved.

---

## 1. Parties and purpose

1.1. These Terms of Confidentiality ("TOC") are between **Layer1Labs
Silicon Inc.** ("Layer1Labs") and the individual and organization
identified in the acceptance token executing these terms (together,
the "Evaluator").

1.2. Layer1Labs is making its ChronoHive storage-admission evaluation
package available to the Evaluator — including the eval API, its
outputs, documentation, and any related materials (the "Eval
Materials") — solely so the Evaluator can evaluate ChronoHive's
storage-admission capability (the "Evaluation Purpose").

## 2. Definitions

2.1. **Confidential Information** means the Eval Materials and everything
the Evaluator learns from them that is not publicly known, including:
(a) the behavior, performance characteristics, and outputs of the eval
API; (b) the contents of the eval repository, documentation, and example
code; (c) any benchmark or measurement results the Evaluator produces
using the Eval Materials; and (d) the API keys, signing keys, and
acceptance tokens used in the evaluation.

2.2. Confidential Information does not include information that the
Evaluator can show (i) was already publicly known through no fault of
the Evaluator, (ii) was independently developed without use of the Eval
Materials, or (iii) was rightfully received from a third party with no
duty of confidentiality.

## 3. Evaluation license

3.1. Layer1Labs grants the Evaluator a limited, non-exclusive,
non-transferable, revocable license to use the Eval Materials **solely
for the Evaluation Purpose**, for the duration of the evaluation
credentials issued to the Evaluator.

3.2. The Evaluator shall not: (a) use the Eval Materials in production
or in any commercial product or service; (b) copy, redistribute, or
sublicense the Eval Materials; (c) reverse-engineer them except to the
extent necessary for the Evaluation Purpose; or (d) remove or alter any
copyright, confidentiality, or honesty notices.

## 4. Confidentiality obligations

4.1. The Evaluator shall keep all Confidential Information strictly
confidential, using at least the same care it uses for its own
confidential information and no less than reasonable care.

4.2. The Evaluator shall not disclose Confidential Information to any
third party, and shall limit internal access to those employees and
contractors who need it for the Evaluation Purpose and who are bound by
confidentiality obligations at least as protective as these terms.

4.3. The Evaluator may use Confidential Information — including
measurement results — internally for the Evaluation Purpose. **Public
disclosure of evaluation results** (including publication, marketing, or
benchmark claims) requires Layer1Labs' prior written consent.

4.4. If the Evaluator is compelled by law to disclose Confidential
Information, it shall give Layer1Labs prompt notice and cooperate to
limit the disclosure.

## 5. Cryptographic execution

5.1. This TOC may be executed cryptographically. An individual executes
this TOC by:

  (a) obtaining the canonical text of this TOC and its SHA-256 digest
      as published by Layer1Labs (via the eval API's `GET /v1/toc`
      endpoint or the canonical `TOC.md` in the eval repository);
  (b) generating an ed25519 signing key pair; and
  (c) producing a digital signature over the canonical acceptance
      message that binds the TOC digest, the signer's API key
      identifier, and the signer's name, organization, and contact
      email, and submitting the resulting acceptance token to the eval
      API's `POST /v1/toc/accept` endpoint.

5.2. An acceptance token whose signature the eval API verifies against
the pinned TOC digest **constitutes execution of this TOC by the
identified signer as of the token's timestamp**, with the same force
and effect as a handwritten signature.

5.3. The signer warrants that they are authorized to bind the
organization named in the acceptance token, and that the identity
information in the token is true and complete. The signing key is the
signer's proof of execution; the signer shall keep its private key
confidential.

5.4. Layer1Labs maintains the verified acceptance tokens as its record
of execution. The Evaluator may request a copy of its acceptance record
at any time.

## 6. Term

6.1. These terms take effect upon execution and the confidentiality
obligations survive for **three (3) years** from the date of the last
disclosure of Confidential Information.

## 7. Intellectual property

7.1. Nothing in these terms transfers any intellectual property right.
Layer1Labs retains all right, title, and interest in the Eval Materials
and in ChronoHive. No license is granted except as expressly stated in
Section 3.

## 8. No warranty; honesty of the evaluation

8.1. The Eval Materials are provided "as is" without warranty of any
kind. Layer1Labs makes no representation that the evaluation simulates
any specific hardware or production environment.

8.2. For the avoidance of doubt, and as stated in the API documentation:
the storage backend, the contention model, and the DDN API surface used
in the evaluation are **simulated**; admission decisions are produced
by the ChronoHive Runtime kernel. Evaluation numbers are simulation
outcomes, not hardware measurements.

## 9. Return of materials

9.1. Upon Layer1Labs' request, or when the evaluation credentials
expire, the Evaluator shall promptly stop using the Eval Materials and
delete or return them, except for one archival copy retained solely to
comply with legal obligations.

## 10. General

10.1. These terms are the entire agreement on their subject matter.
Amendments must be in writing signed by both parties.

10.2. If any provision is held unenforceable, the rest remain in effect.

10.3. Governing law: **[to be completed by counsel]**.

10.4. Neither party may assign these terms without the other's written
consent, except in connection with a merger or sale of substantially
all of its assets.

---

*Executed cryptographically per Section 5. The eval API activates an
API key only after verifying a valid acceptance token — see
`docs/API.md` ("Executing the TOC") and `tools/sign_toc.py`.*

© 2026 Layer1Labs Silicon Inc. All rights reserved. CONFIDENTIAL.
