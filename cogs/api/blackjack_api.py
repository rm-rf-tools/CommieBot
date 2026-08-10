import random
from enum import Enum

class GameState(Enum):
    PLAYING = "playing"
    PLAYER_WON = "player_won"
    DEALER_WON = "dealer_won"
    TIE = "tie"
    PLAYER_BUSTED = "player_busted"
    DEALER_BUSTED = "dealer_busted"
    PLAYER_BLACKJACK = "player_blackjack"

class Card:
    def __init__(self, suit, rank):
        self.suit = suit
        self.rank = rank

    @property
    def value(self):
        if self.rank in ['J', 'Q', 'K']:
            return 10
        if self.rank == 'A':
            return 11 # Hand class handles the adjustment to 1
        return int(self.rank)

    def __str__(self):
        return f"{self.rank} of {self.suit}"

class Deck:
    def __init__(self, num_decks=1):
        suits = ['Hearts', 'Diamonds', 'Clubs', 'Spades']
        ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
        self.cards = [Card(s, r) for s in suits for r in ranks] * num_decks
        random.shuffle(self.cards)

    def draw(self):
        if not self.cards:
            raise ValueError("The deck is empty!")
        return self.cards.pop()

class Hand:
    def __init__(self):
        self.cards = []

    def add_card(self, card):
        self.cards.append(card)

    @property
    def score(self):
        total = sum(c.value for c in self.cards)
        aces = sum(1 for c in self.cards if c.rank == 'A')
        
        # Adjust for Aces if score is over 21
        while total > 21 and aces > 0:
            total -= 10
            aces -= 1
            
        return total

    def is_blackjack(self):
        return len(self.cards) == 2 and self.score == 21

    def is_busted(self):
        return self.score > 21

class BlackjackGame:
    def __init__(self, bet_amount=0):
        self.deck = Deck(num_decks=1)
        self.player_hand = Hand()
        self.dealer_hand = Hand()
        self.state = GameState.PLAYING
        self.bet = bet_amount
        self.doubled_down = False
        
        self._initial_deal()

    def _initial_deal(self):
        # Deal two cards to player and dealer
        for _ in range(2):
            self.player_hand.add_card(self.deck.draw())
            self.dealer_hand.add_card(self.deck.draw())

        # Check for immediate blackjacks
        p_bj = self.player_hand.is_blackjack()
        d_bj = self.dealer_hand.is_blackjack()

        if p_bj and d_bj:
            self.state = GameState.TIE
        elif p_bj:
            self.state = GameState.PLAYER_BLACKJACK
        elif d_bj:
            self.state = GameState.DEALER_WON

    def hit(self):
        if self.state != GameState.PLAYING:
            return self.state

        self.player_hand.add_card(self.deck.draw())
        
        if self.player_hand.is_busted():
            self.state = GameState.PLAYER_BUSTED
            
        return self.state

    def double_down(self):
        """
        Doubles the bet, hits exactly once, and forces a stand.
        Can only be done on the initial two cards.
        """
        if self.state != GameState.PLAYING:
            return self.state
            
        if len(self.player_hand.cards) != 2:
            raise ValueError("You can only double down on your first turn.")

        self.doubled_down = True
        self.bet *= 2
        self.hit()
        
        # If the single hit didn't bust the player, automatically stand
        if self.state == GameState.PLAYING:
            self.stand()
            
        return self.state

    def stand(self):
        if self.state != GameState.PLAYING:
            return self.state

        # Dealer rules: Must hit until score is 17 or higher
        while self.dealer_hand.score < 17:
            self.dealer_hand.add_card(self.deck.draw())

        self._evaluate_winner()
        return self.state

    def _evaluate_winner(self):
        p_score = self.player_hand.score
        d_score = self.dealer_hand.score

        if self.dealer_hand.is_busted():
            self.state = GameState.DEALER_BUSTED
        elif p_score > d_score:
            self.state = GameState.PLAYER_WON
        elif d_score > p_score:
            self.state = GameState.DEALER_WON
        else:
            self.state = GameState.TIE

    def get_dealer_visible_card(self):
        """Returns the single face-up card for the dealer during active play."""
        return self.dealer_hand.cards[0]


# # 1. User types /blackjack 100
# game = BlackjackGame(bet_amount=100)

# print(f"Dealer shows: {game.get_dealer_visible_card()}")
# print(f"You have: {[str(c) for c in game.player_hand.cards]} (Score: {game.player_hand.score})")

# # Check if game ended immediately (e.g., Blackjack on deal)
# if game.state != GameState.PLAYING:
#     print(f"Game Over! Status: {game.state.value}")

# # 2. User clicks the "Double Down" button on Discord
# try:
#     game.double_down()
# except ValueError as e:
#     print(e)

# # 3. Game calculates the single hit and the dealer's turn automatically
# print(f"Your final hand: {[str(c) for c in game.player_hand.cards]} (Score: {game.player_hand.score})")
# print(f"Dealer's final hand: {[str(c) for c in game.dealer_hand.cards]} (Score: {game.dealer_hand.score})")

# # 4. Process the payout based on state
# if game.state in [GameState.PLAYER_WON, GameState.DEALER_BUSTED]:
#     print(f"You win! Payout: {game.bet * 2} coins.")
# elif game.state == GameState.PLAYER_BLACKJACK:
#     print(f"Blackjack! Payout: {game.bet * 2.5} coins.") # Standard 3:2 payout
# elif game.state == GameState.TIE:
#     print(f"Push. Your {game.bet} coins are returned.")
# else:
#     print(f"You lost your bet of {game.bet} coins.")