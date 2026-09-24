#pragma once
UCLASS()
class ADemoState : public AGameStateBase
{
    GENERATED_BODY()
private:
    UPROPERTY(Replicated) int32 RoundScore;
};
