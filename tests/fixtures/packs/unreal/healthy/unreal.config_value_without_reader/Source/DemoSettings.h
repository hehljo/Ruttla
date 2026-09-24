#pragma once
UCLASS(Config=Game)
class UDemoSettings : public UDeveloperSettings
{
    GENERATED_BODY()
public:
    UPROPERTY(Config, EditAnywhere) float RoundSeconds;
};
