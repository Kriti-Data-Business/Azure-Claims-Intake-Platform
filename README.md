# Azure-Claims-Intake-Platform
Event-driven AI intake service in Python. A FastAPI API publishes to Azure Service Bus using managed identity, an Azure Functions consumer processes messages, and Azure OpenAI performs structured extraction with human-review routing. Built with pytest tests, Docker, Bicep infrastructure-as-code and a GitHub Actions CI pipeline
