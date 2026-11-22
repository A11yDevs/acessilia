"""The core's adapters over the Toolbox, through the SDK (ADR-0016, step 2).

``toolbox_client`` maps the run's ``ToolboxConfig`` to the SDK's client
configuration and builds clients (ADR-0016, step 3); it does not re-export the
SDK API. ``toolbox_math_tools`` recognizes, converts and speaks formulas;
``media_inspect`` inspects the source; ``pdf_ua_audit`` audits an exported
PDF; ``text_spans`` reads the PDF text layer; ``vision_payload`` reduces a
vision payload through the render capability. Gathered here from
``backend/tools``.
"""
